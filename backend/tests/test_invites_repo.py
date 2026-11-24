"""The database side of the invitations: written, committed, correctly conditioned."""

from datetime import datetime

import pytest

from src.features.invites import repository as repo

ABLAUF = datetime(2026, 9, 1, 12, 0, 0)


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


def test_creating_an_invite_commits(fake_db):
    calls = fake_db(rows=[(7,)])

    neu = repo.create_invite(
        token="tok",
        email="a@example.org",
        uid="a",
        role="staff",
        custom_role_id=None,
        created_by=1,
        expires_at=ABLAUF,
    )

    assert neu == 7
    assert ("commit", None, None) in calls, "ohne commit sieht der naechste Aufruf nichts"


def test_reading_an_unknown_token_returns_nothing(fake_db):
    calls = fake_db(rows=[])
    assert repo.get_invite_by_token("gibtsnicht") is None
    anweisungen = [c[1] for c in calls if c[0] == "execute"]
    assert any("WHERE token = %s" in a for a in anweisungen)


def test_marking_used_only_touches_an_open_invite(fake_db):
    calls = fake_db(rows=[(5,)])

    assert repo.mark_invite_used(5) is True

    anweisungen = [c[1] for c in calls if c[0] == "execute"]
    assert any("used_at IS NULL" in a for a in anweisungen), "sonst laesst sich ein Link zweimal einloesen"
    assert any("expires_at > NOW()" in a for a in anweisungen), "an invite that ran out mid-request must not redeem"
    assert ("commit", None, None) in calls


def test_marking_an_already_used_invite_reports_failure(fake_db):
    fake_db(rows=[])
    assert repo.mark_invite_used(5) is False


def test_listing_shows_the_newest_first(fake_db):
    calls = fake_db(rows=[])
    assert repo.list_invites() == []
    anweisungen = [c[1] for c in calls if c[0] == "execute"]
    assert any("ORDER BY created_at DESC" in a for a in anweisungen)


def test_withdrawing_deletes_and_commits(fake_db):
    calls = fake_db(rows=[(5,)])
    assert repo.delete_invite(5) is True
    anweisungen = [c[1] for c in calls if c[0] == "execute"]
    assert any("DELETE FROM invites" in a for a in anweisungen)
    assert ("commit", None, None) in calls


def test_reopening_clears_the_stamp_and_commits(fake_db):
    calls = fake_db()
    repo.reopen_invite(5)
    anweisungen = [c[1] for c in calls if c[0] == "execute"]
    assert any("used_at = NULL" in a for a in anweisungen)
    assert ("commit", None, None) in calls
