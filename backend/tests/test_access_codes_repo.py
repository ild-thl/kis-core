"""The database side of the access codes: written, committed, correctly conditioned."""

from datetime import datetime

import pytest

from src.features.access_codes import repository as repo

ABLAUF = datetime(2026, 9, 30, 12, 0, 0)


class _FakeCursor:
    def __init__(self, rows, calls):
        self._rows = list(rows)
        self._calls = calls
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._calls.append(("execute", " ".join(sql.split()), params))
        self.rowcount = 1

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self, rows, calls):
        self._rows = rows
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self, **kwargs):
        return _FakeCursor(self._rows, self._calls)

    def commit(self):
        self._calls.append(("commit", None, None))


@pytest.fixture
def fake_db(monkeypatch):
    def _apply(rows=()):
        calls: list[tuple] = []
        monkeypatch.setattr(repo, "get_connection", lambda: _FakeConn(rows, calls))
        return calls
    return _apply


def test_creating_a_code_commits(fake_db):
    calls = fake_db(rows=[(7,)])

    neu = repo.create_code(
        code="ASKF-4K2P-7RXM",
        label="Kollegen August",
        role="staff",
        custom_role_id=None,
        max_uses=50,
        valid_until=ABLAUF,
        access_hours=336,
        show_credentials=True,
        show_evaluation=False,
        created_by=1,
    )

    assert neu == 7
    assert ("commit", None, None) in calls, "ohne commit sieht der naechste Aufruf nichts"


def test_creating_a_code_stores_the_hours_and_the_credentials_switch(fake_db):
    calls = fake_db(rows=[(7,)])

    repo.create_code(
        code="ASKF-4K2P-7RXM",
        label="Tag der Lehre",
        role="user",
        custom_role_id=None,
        max_uses=500,
        valid_until=ABLAUF,
        access_hours=12,
        show_credentials=False,
        show_evaluation=False,
        created_by=1,
    )

    anweisung = [c for c in calls if c[0] == "execute"][0]
    assert "access_hours" in anweisung[1]
    assert "show_credentials" in anweisung[1]
    assert 12 in anweisung[2]
    assert False in anweisung[2]


def test_creating_a_code_stores_the_evaluation_switch(fake_db):
    calls = fake_db(rows=[(7,)])

    repo.create_code(
        code="ASKF-4K2P-7RXM",
        label="Tag der Lehre",
        role="user",
        custom_role_id=None,
        max_uses=500,
        valid_until=ABLAUF,
        access_hours=12,
        show_credentials=False,
        show_evaluation=True,
        created_by=1,
    )

    anweisung = [c for c in calls if c[0] == "execute"][0]
    assert "show_evaluation" in anweisung[1]
    assert True in anweisung[2]


def test_shows_evaluation_asks_for_the_code_behind_the_account(fake_db):
    calls = fake_db(rows=[(1,)])

    assert repo.shows_evaluation(42) is True

    anweisung = [c for c in calls if c[0] == "execute"][0]
    assert "access_code_id" in anweisung[1]
    assert "show_evaluation" in anweisung[1]
    assert 42 in anweisung[2]


def test_shows_evaluation_is_false_without_a_code(fake_db):
    fake_db(rows=[])
    assert repo.shows_evaluation(42) is False


def test_claim_use_only_counts_up_while_the_code_has_room(fake_db):
    calls = fake_db(rows=[(7,)])

    assert repo.claim_use(7) is True

    anweisungen = [c[1] for c in calls if c[0] == "execute"]
    assert any("used_count < max_uses" in a for a in anweisungen), "sonst platzt die Obergrenze"
    assert any("valid_until > NOW()" in a for a in anweisungen)
    assert any("active" in a for a in anweisungen)
    assert ("commit", None, None) in calls


def test_claim_use_reports_failure_when_nothing_changed(fake_db):
    fake_db(rows=[])
    assert repo.claim_use(7) is False


def test_release_use_never_goes_below_zero(fake_db):
    calls = fake_db()

    repo.release_use(7)

    anweisungen = [c[1] for c in calls if c[0] == "execute"]
    assert any("used_count = used_count - 1" in a for a in anweisungen)
    assert any("used_count > 0" in a for a in anweisungen)


def test_deleting_a_code_never_touches_the_users_table(fake_db):
    calls = fake_db(rows=[(7,)])

    assert repo.delete_code(7) is True

    anweisungen = [c[1] for c in calls if c[0] == "execute"]
    assert any("DELETE FROM access_codes" in a for a in anweisungen)
    assert not any("users" in a for a in anweisungen), "Loeschen darf nie ein Konto anfassen"


def test_get_code_by_id_returns_none_when_missing(fake_db):
    fake_db(rows=[])
    assert repo.get_code_by_id(999) is None


def test_get_code_by_id_returns_the_row(fake_db):
    zeile = {"id": 7, "code": "ASKF-4K2P-7RXM", "label": "Kollegen August", "max_uses": 50, "used_count": 3}
    fake_db(rows=[zeile])
    assert repo.get_code_by_id(7) == zeile


def test_updating_a_code_commits_and_leaves_code_and_used_count_untouched(fake_db):
    calls = fake_db(rows=[(7,)])

    getroffen = repo.update_code(
        7,
        label="Neuer Titel",
        role="user",
        custom_role_id=None,
        max_uses=25,
        valid_until=ABLAUF,
        access_hours=None,
        show_credentials=True,
        show_evaluation=False,
    )

    assert getroffen is True
    anweisungen = [c[1] for c in calls if c[0] == "execute"]
    assert any("UPDATE access_codes" in a for a in anweisungen)
    assert any("access_hours" in a for a in anweisungen)
    assert any("show_credentials" in a for a in anweisungen)
    assert not any("SET code" in a for a in anweisungen), "der Code selbst darf sich nie aendern"
    assert not any("used_count = %s" in a for a in anweisungen), "der Zaehler gehoert claim_use, nicht dem Editieren"
    assert ("commit", None, None) in calls


def test_updating_a_code_writes_the_evaluation_switch(fake_db):
    calls = fake_db(rows=[(7,)])

    repo.update_code(
        7,
        label="Tag der Lehre",
        role="user",
        custom_role_id=None,
        max_uses=25,
        valid_until=ABLAUF,
        access_hours=12,
        show_credentials=True,
        show_evaluation=True,
    )

    anweisungen = [c for c in calls if c[0] == "execute"]
    assert any("show_evaluation" in a[1] for a in anweisungen)
    assert any(True in a[2] for a in anweisungen)


def test_updating_a_code_refuses_to_drop_max_uses_below_used_count(fake_db):
    calls = fake_db(rows=[])

    getroffen = repo.update_code(
        7,
        label="Neuer Titel",
        role="user",
        custom_role_id=None,
        max_uses=1,
        valid_until=ABLAUF,
        access_hours=None,
        show_credentials=True,
        show_evaluation=False,
    )

    assert getroffen is False
    anweisungen = [c[1] for c in calls if c[0] == "execute"]
    assert any(">= used_count" in a for a in anweisungen)


def test_lock_expired_accounts_only_touches_active_ones_past_their_deadline(fake_db):
    calls = fake_db(rows=[(42,), (43,)])

    gesperrt = repo.lock_expired_accounts()

    assert gesperrt == 2
    anweisung = [c for c in calls if c[0] == "execute"][0]
    assert "UPDATE users" in anweisung[1]
    # users.active is an integer column, see the real database test below.
    assert "SET active = 0" in anweisung[1]
    assert "access_expires_at <= NOW()" in anweisung[1]
    assert "access_code_id IS NOT NULL" in anweisung[1]
    assert "active" in anweisung[1]
    assert ("commit", None, None) in calls


def test_set_user_access_writes_both_columns(fake_db):
    calls = fake_db()
    frist = datetime(2026, 9, 11, 12, 0, 0)

    repo.set_user_access(42, expires_at=frist, code_id=7)

    befehl = [c for c in calls if c[0] == "execute"][0]
    assert "access_expires_at" in befehl[1] and "access_code_id" in befehl[1]
    assert befehl[2] == (frist, 7, 42)


def test_lock_expired_accounts_laeuft_gegen_die_echte_datenbank(monkeypatch):
    """users.active is an integer, so the hourly "argument of AND must be type boolean" error meant no expired test account was ever locked."""
    import os
    from contextlib import contextmanager

    import psycopg2

    echt = psycopg2.connect(os.environ["DATABASE_URL"])

    class _OhneCommit:
        """Everything runs inside one transaction that is thrown away at the end."""

        def cursor(self, *a, **k):
            return echt.cursor(*a, **k)

        def commit(self):
            pass

    @contextmanager
    def verbindung():
        yield _OhneCommit()

    monkeypatch.setattr(repo, "get_connection", verbindung)
    try:
        assert repo.lock_expired_accounts() >= 0
    finally:
        echt.rollback()
        echt.close()
