"""Nightly database backup into object storage, daily, weekly and monthly."""

import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from src.celery_app import celery_app
from src.limits import (
    DB_BACKUP_KEEP_DAYS,
    DB_BACKUP_KEEP_MONTHS,
    DB_BACKUP_KEEP_WEEKS,
    DB_BACKUP_TIME_LIMIT_SECONDS,
)
from src.storage import copy_key, delete_file, list_keys, put_file

_DAILY = "backups/daily/"
_WEEKLY = "backups/weekly/"
_MONTHLY = "backups/monthly/"


def _dump_command_and_env() -> tuple[list[str], dict]:
    """Builds the pg_dump call, the password goes through the environment."""
    url = urlparse(os.environ["DATABASE_URL"])
    cmd = [
        "pg_dump",
        "-h", url.hostname or "postgres",
        "-p", str(url.port or 5432),
        "-U", url.username or "askf",
        "-d", (url.path or "/askf").lstrip("/"),
        # Custom format with compression so single tables can be restored.
        "-Fc", "-Z6",
    ]
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    return cmd, env


def _prune_old(prefix: str, keep: int) -> int:
    """Deletes old backups except the newest, sorted by name."""
    keys = sorted(k for k in list_keys(prefix) if k.endswith(".dump"))
    if len(keys) <= keep:
        return 0
    veraltet = keys[:-keep]
    for k in veraltet:
        try:
            delete_file(k)
        except Exception as e:
            logger.warning("Alte Sicherung {} nicht loeschbar: {}", k, e)
    return len(veraltet)


def _period_copy_missing(prefix: str, label: str) -> bool:
    """True when there is no copy for this period yet."""
    return not any(k.endswith(f"askfrancis-{label}.dump") for k in list_keys(prefix))


@celery_app.task(
    name="backup.database",
    queue="long",
    time_limit=DB_BACKUP_TIME_LIMIT_SECONDS,
    soft_time_limit=DB_BACKUP_TIME_LIMIT_SECONDS - 60,
)
def run_database_backup() -> dict:
    """One pg_dump, into the bucket, clear old backups away."""
    jetzt = datetime.now(timezone.utc)
    tag = jetzt.strftime("%Y-%m-%d")
    # ISO week, so the turn of the year produces no duplicate names.
    woche = jetzt.strftime("%G-W%V")
    monat = jetzt.strftime("%Y-%m")
    key = f"{_DAILY}askfrancis-{tag}.dump"
    cmd, env = _dump_command_and_env()
    begonnen = time.time()

    with tempfile.TemporaryDirectory(prefix="askf_backup_") as tmp:
        ziel = str(Path(tmp) / "db.dump")
        try:
            subprocess.run(
                cmd + ["-f", ziel],
                env=env,
                check=True,
                capture_output=True,
                timeout=DB_BACKUP_TIME_LIMIT_SECONDS - 120,
            )
        except subprocess.CalledProcessError as e:
            # Pass stderr along, otherwise the log only says 'exit 1'.
            logger.error("pg_dump fehlgeschlagen: {}", (e.stderr or b"")[:500].decode(errors="replace"))
            raise
        except subprocess.TimeoutExpired:
            logger.error("pg_dump hat die Zeitgrenze ueberschritten")
            raise

        groesse = Path(ziel).stat().st_size
        if groesse == 0:
            # Uploading an empty file would be worse than none.
            raise RuntimeError("pg_dump lieferte eine leere Datei, Sicherung verworfen")

        put_file(key, ziel)

    dauer = time.time() - begonnen

    # Pull the weekly and monthly copy server side, that saves the network.
    kopien = {}
    for stufe, prefix, label in (("weekly", _WEEKLY, woche), ("monthly", _MONTHLY, monat)):
        if not _period_copy_missing(prefix, label):
            kopien[stufe] = None
            continue
        ziel_key = f"{prefix}askfrancis-{label}.dump"
        try:
            copy_key(key, ziel_key)
            kopien[stufe] = ziel_key
        except Exception as e:
            # The daily backup is already there, that is the more important part.
            logger.warning("Kopie {} fehlgeschlagen: {}", ziel_key, e)
            kopien[stufe] = None

    entfernt = {
        "daily": _prune_old(_DAILY, DB_BACKUP_KEEP_DAYS),
        "weekly": _prune_old(_WEEKLY, DB_BACKUP_KEEP_WEEKS),
        "monthly": _prune_old(_MONTHLY, DB_BACKUP_KEEP_MONTHS),
    }
    zusatz = ", ".join(v for v in kopien.values() if v)
    logger.info(
        "Datenbank-Sicherung {} abgelegt ({:.0f} MB in {:.0f}s){}, entfernt: {}",
        key, groesse / 1024 / 1024, dauer,
        f", zusaetzlich {zusatz}" if zusatz else "",
        entfernt,
    )
    return {"key": key, "bytes": groesse, "seconds": round(dauer),
            "copies": kopien, "pruned": entfernt}
