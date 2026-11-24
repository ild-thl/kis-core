"""Checks call construction, password handling and retention of the backup."""

import pytest

from src.tasks import backup_tasks


# ─── Aufrufbau ─────────────────────────────────────────────────────────────

def test_dump_command_reads_host_port_user_and_db_from_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://askfuser:geheim@dbhost:6543/askfdb")
    cmd, env = backup_tasks._dump_command_and_env()
    assert cmd[0] == "pg_dump"
    assert "-h" in cmd and cmd[cmd.index("-h") + 1] == "dbhost"
    assert "-p" in cmd and cmd[cmd.index("-p") + 1] == "6543"
    assert "-U" in cmd and cmd[cmd.index("-U") + 1] == "askfuser"
    assert "-d" in cmd and cmd[cmd.index("-d") + 1] == "askfdb"


def test_password_never_lands_in_the_arguments(monkeypatch):
    """Arguments are visible to everyone, another process's environment is not."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://askfuser:geheim@dbhost:5432/askfdb")
    cmd, env = backup_tasks._dump_command_and_env()
    assert "geheim" not in " ".join(cmd)
    assert env["PGPASSWORD"] == "geheim"


def test_dump_uses_custom_format_so_single_tables_can_be_restored(monkeypatch):
    """The plain SQL format cannot do ``pg_restore -t``, hence -Fc."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/d")
    cmd, _ = backup_tasks._dump_command_and_env()
    assert "-Fc" in cmd


def test_missing_password_in_url_leaves_pgpassword_unset(monkeypatch):
    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@h:5432/d")
    _, env = backup_tasks._dump_command_and_env()
    assert "PGPASSWORD" not in env


# ─── Aufbewahrung ──────────────────────────────────────────────────────────

def test_prune_keeps_the_newest_and_deletes_the_rest(monkeypatch):
    vorhanden = [
        "backups/askfrancis-2026-07-24.dump",
        "backups/askfrancis-2026-07-25.dump",
        "backups/askfrancis-2026-07-26.dump",
        "backups/askfrancis-2026-07-27.dump",
    ]
    geloescht = []
    monkeypatch.setattr(backup_tasks, "list_keys", lambda p: list(vorhanden))
    monkeypatch.setattr(backup_tasks, "delete_file", lambda k: geloescht.append(k))

    entfernt = backup_tasks._prune_old(backup_tasks._DAILY, keep=2)

    assert entfernt == 2
    # Sorted alphabetically is sorted chronologically here.
    assert geloescht == ["backups/askfrancis-2026-07-24.dump", "backups/askfrancis-2026-07-25.dump"]


def test_prune_does_nothing_when_within_retention(monkeypatch):
    monkeypatch.setattr(backup_tasks, "list_keys", lambda p: ["backups/daily/askfrancis-2026-07-27.dump"])
    monkeypatch.setattr(backup_tasks, "delete_file", lambda k: pytest.fail("darf nicht loeschen"))
    assert backup_tasks._prune_old(backup_tasks._DAILY, keep=7) == 0


def test_prune_ignores_foreign_files_in_the_prefix(monkeypatch):
    """Whatever does not end in .dump is not touched."""
    geloescht = []
    monkeypatch.setattr(backup_tasks, "list_keys", lambda p: [
        "backups/askfrancis-2026-07-24.dump",
        "backups/askfrancis-2026-07-25.dump",
        "backups/README.txt",
    ])
    monkeypatch.setattr(backup_tasks, "delete_file", lambda k: geloescht.append(k))
    backup_tasks._prune_old(backup_tasks._DAILY, keep=1)
    assert geloescht == ["backups/askfrancis-2026-07-24.dump"]


def test_prune_survives_a_failing_delete(monkeypatch):
    """A failed delete must not turn the backup into an error."""
    def kaputt(_):
        raise RuntimeError("Bucket sagt nein")
    monkeypatch.setattr(backup_tasks, "list_keys", lambda p: [
        "backups/askfrancis-2026-07-24.dump", "backups/askfrancis-2026-07-25.dump",
    ])
    monkeypatch.setattr(backup_tasks, "delete_file", kaputt)
    assert backup_tasks._prune_old(backup_tasks._DAILY, keep=1) == 1


# ─── Monatskopie ───────────────────────────────────────────────────────────

def test_period_copy_is_made_when_the_period_has_none(monkeypatch):
    monkeypatch.setattr(backup_tasks, "list_keys", lambda p: [])
    assert backup_tasks._period_copy_missing(backup_tasks._MONTHLY, "2026-07") is True
    assert backup_tasks._period_copy_missing(backup_tasks._WEEKLY, "2026-W31") is True


def test_period_copy_is_skipped_when_it_already_exists(monkeypatch):
    monkeypatch.setattr(backup_tasks, "list_keys",
                        lambda p: ["backups/monthly/askfrancis-2026-07.dump"])
    assert backup_tasks._period_copy_missing(backup_tasks._MONTHLY, "2026-07") is False


def test_period_copy_is_made_when_only_other_periods_exist(monkeypatch):
    """The new period needs its own copy, even when older ones exist."""
    monkeypatch.setattr(backup_tasks, "list_keys", lambda p: [
        "backups/monthly/askfrancis-2026-05.dump",
        "backups/monthly/askfrancis-2026-06.dump",
    ])
    assert backup_tasks._period_copy_missing(backup_tasks._MONTHLY, "2026-07") is True


def test_all_three_tiers_live_in_separate_folders():
    """The prefixes have to stay separate, otherwise the tiering breaks."""
    stufen = [backup_tasks._DAILY, backup_tasks._WEEKLY, backup_tasks._MONTHLY]
    assert len(set(stufen)) == 3
    for a in stufen:
        for b in stufen:
            if a is not b:
                assert not a.startswith(b)


def test_week_label_uses_iso_week_so_new_year_has_no_duplicates():
    """With the wrong year format the new year week would get two names."""
    from datetime import datetime, timezone
    silvester = datetime(2025, 12, 29, tzinfo=timezone.utc)   # ISO-Woche 1 von 2026
    assert silvester.strftime("%G-W%V") == "2026-W01"
