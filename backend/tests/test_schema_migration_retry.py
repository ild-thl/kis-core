"""A lock conflict during migration must not stop the backend from starting."""

import psycopg2
import pytest

from src.core.db import schema


@pytest.fixture(autouse=True)
def kein_warten(monkeypatch):
    """Remove the pause between attempts, otherwise the test takes seconds."""
    monkeypatch.setattr("time.sleep", lambda _s: None)


def test_a_lock_conflict_is_retried_instead_of_killing_the_start(monkeypatch):
    laeufe = {"n": 0}

    def _flaky(_admin_email=None):
        laeufe["n"] += 1
        if laeufe["n"] == 1:
            raise psycopg2.errors.DeadlockDetected("deadlock detected")

    monkeypatch.setattr(schema, "_init_db", _flaky)
    schema.init_db()  # darf nicht werfen
    assert laeufe["n"] == 2


def test_a_lock_timeout_is_retried_too(monkeypatch):
    # With lock_timeout set Postgres reports LockNotAvailable instead of blocking.
    laeufe = {"n": 0}

    def _flaky(_admin_email=None):
        laeufe["n"] += 1
        if laeufe["n"] < 3:
            raise psycopg2.errors.LockNotAvailable("canceling statement due to lock timeout")

    monkeypatch.setattr(schema, "_init_db", _flaky)
    schema.init_db()
    assert laeufe["n"] == 3


def test_it_gives_up_after_the_last_attempt(monkeypatch):
    # At some point the error has to become visible.
    laeufe = {"n": 0}

    def _immer_blockiert(_admin_email=None):
        laeufe["n"] += 1
        raise psycopg2.errors.DeadlockDetected("deadlock detected")

    monkeypatch.setattr(schema, "_init_db", _immer_blockiert)
    with pytest.raises(psycopg2.errors.DeadlockDetected):
        schema.init_db()
    assert laeufe["n"] == schema._MIGRATION_ATTEMPTS


def test_a_real_error_is_not_retried(monkeypatch):
    """A typo in the schema should show up right away, not be retried five times."""
    laeufe = {"n": 0}

    def _kaputt(_admin_email=None):
        laeufe["n"] += 1
        raise psycopg2.errors.SyntaxError("syntax error at or near")

    monkeypatch.setattr(schema, "_init_db", _kaputt)
    with pytest.raises(psycopg2.errors.SyntaxError):
        schema.init_db()
    assert laeufe["n"] == 1


def test_the_admin_email_reaches_the_migration(monkeypatch):
    gesehen = {}
    monkeypatch.setattr(schema, "_init_db",
                        lambda admin_email=None: gesehen.update(mail=admin_email))
    schema.init_db(admin_email="admin@example.org")
    assert gesehen["mail"] == "admin@example.org"
