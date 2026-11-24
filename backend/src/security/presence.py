"""Records who is here right now and which days someone was here."""
import time
from datetime import datetime, timezone

from loguru import logger

from src.core.redis_url import REDIS_URL
from src.core.db.pool import get_connection

_PREFIX = "askf:seen:"

# A value below this mark cannot be a timestamp.
_FRUEHESTENS = 1_600_000_000  # September 2020

# How long a heartbeat counts.
TTL_SECONDS = 300

_client = None


def _redis():
    global _client
    if _client is None:
        import redis as _redis_lib
        _client = _redis_lib.from_url(
            REDIS_URL, socket_connect_timeout=1, socket_timeout=1
        )
    return _client


def touch(user_id: int) -> None:
    """A heartbeat, the key holds the moment of the first one."""
    if user_id <= 0:
        return
    try:
        r = _redis()
        schluessel = f"{_PREFIX}{user_id}"
        r.set(schluessel, str(int(time.time())), nx=True, ex=TTL_SECONDS)
        r.expire(schluessel, TTL_SECONDS)
    except Exception as e:
        logger.warning("Anwesenheit nicht gemerkt (user={}): {}", user_id, e)


def online_since() -> dict[int, int]:
    """User id to the moment of the first heartbeat, empty on failure."""
    try:
        r = _redis()
        keys = r.keys(f"{_PREFIX}*")
        if not keys:
            return {}
        werte = r.mget(keys)
        ergebnis: dict[int, int] = {}
        for k, v in zip(keys, werte):
            if v is None:
                continue
            try:
                nummer = int(k.decode().rsplit(":", 1)[1])
                zeitpunkt = int(v)
            except (ValueError, AttributeError):
                continue
            ergebnis[nummer] = zeitpunkt if zeitpunkt >= _FRUEHESTENS else int(time.time())
        return ergebnis
    except Exception as e:
        logger.warning("Anwesenheit nicht lesbar: {}", e)
        return {}


def mark_hour(user_id: int) -> None:
    """Records this hour for this user, at most one row per hour."""
    if user_id <= 0:
        return
    jetzt = datetime.now(timezone.utc)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO user_presence (user_id, day, hour)
                       VALUES (
                           %s,
                           (%s AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Berlin')::date,
                           EXTRACT(HOUR FROM (%s AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Berlin'))
                       )
                       ON CONFLICT (user_id, day, hour) DO NOTHING""",
                    (user_id, jetzt, jetzt),
                )
            conn.commit()
    except Exception as e:
        logger.warning("Anwesenheitsstunde nicht gemerkt (user={}): {}", user_id, e)
