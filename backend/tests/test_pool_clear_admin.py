"""Clear pools platform wide without hollowing out finished sets or duplicating appointments."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.features.ai_assistant.repository import exercise_pool as pool_repo
from src.features.ai_assistant.repository import schedule as schedule_repo
from src.features.ai_assistant.repository import schedule_jobs as schedule_jobs_repo


class _FakeCursor:
    def __init__(self, rows, calls):
        self._rows = list(rows)
        self._calls = calls
        self.rowcount = 3

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._calls.append(("execute", " ".join(sql.split()), params))

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
def fake_pool_db(monkeypatch):
    def _apply(rows=()):
        calls: list[tuple] = []
        monkeypatch.setattr(pool_repo, "get_connection", lambda: _FakeConn(rows, calls))
        return calls
    return _apply


@pytest.fixture
def fake_schedule_db(monkeypatch):
    def _apply(rows=()):
        calls: list[tuple] = []
        monkeypatch.setattr(schedule_jobs_repo, "get_connection", lambda: _FakeConn(rows, calls))
        return calls
    return _apply


def _anweisungen(calls):
    return [c[1] for c in calls if c[0] == "execute"]


# --- Aufgaben-Vorrat leeren ----------------------------------------------------

def test_clearing_a_tool_writes_the_content_back_before_deleting(fake_pool_db):
    """Otherwise a finished set would be left without answers."""
    calls = fake_pool_db()
    pool_repo.clear_pool_for_tools(["quiz"])
    sql = _anweisungen(calls)
    assert sql[0].startswith("UPDATE aia_exercise_items"), "erst zurueckschreiben"
    assert any("DELETE FROM aia_exercise_pool" in a for a in sql)


def test_clearing_a_tool_covers_every_workspace(fake_pool_db):
    """The button clears platform wide, a source condition would be a step back."""
    calls = fake_pool_db()
    pool_repo.clear_pool_for_tools(["quiz"])
    loeschung = next(a for a in _anweisungen(calls) if "DELETE FROM aia_exercise_pool" in a)
    assert "source_id" not in loeschung
    assert "workspace" not in loeschung


def test_clearing_takes_only_the_chosen_tools(fake_pool_db):
    calls = fake_pool_db()
    pool_repo.clear_pool_for_tools(["quiz", "grammatik"])
    loeschung = next(
        (a, p) for a, p in
        [(c[1], c[2]) for c in calls if c[0] == "execute"]
        if "DELETE FROM aia_exercise_pool" in a
    )
    assert "tool = ANY" in loeschung[0]
    assert ["quiz", "grammatik"] in loeschung[1]


def test_clearing_an_unknown_tool_is_refused(fake_pool_db):
    """A typo must not silently delete nothing and report success."""
    fake_pool_db()
    with pytest.raises(ValueError):
        pool_repo.clear_pool_for_tools(["gibtsnicht"])


def test_clearing_nothing_touches_no_connection(monkeypatch):
    def boom():
        raise AssertionError("es wurde kein Werkzeug gewaehlt")

    monkeypatch.setattr(pool_repo, "get_connection", boom)
    assert pool_repo.clear_pool_for_tools([]) == 0


def test_clearing_commits(fake_pool_db):
    calls = fake_pool_db()
    pool_repo.clear_pool_for_tools(["quiz"])
    assert ("commit", None, None) in calls


# --- Zahlen --------------------------------------------------------------------

def test_the_counts_come_grouped_by_tool(fake_pool_db):
    fake_pool_db(rows=[("quiz", 12), ("grammatik", 5)])
    assert pool_repo.pool_counts_by_tool() == {"quiz": 12, "grammatik": 5}


# --- Zeitplan ------------------------------------------------------------------

def test_clearing_the_schedule_pool_leaves_the_processed_marker(fake_schedule_db):
    """If the marker goes too, the next run creates the same appointments again."""
    calls = fake_schedule_db()
    schedule_repo.clear_source_extractions()
    sql = " ".join(_anweisungen(calls))
    assert "DELETE FROM aia_schedule_source_extractions" in sql
    assert "aia_schedule_processed_sources" not in sql
    assert "aia_schedule_entries" not in sql


def test_clearing_the_schedule_pool_commits(fake_schedule_db):
    calls = fake_schedule_db()
    schedule_repo.clear_source_extractions()
    assert ("commit", None, None) in calls


def test_the_schedule_pool_size_is_read(fake_schedule_db):
    fake_schedule_db(rows=[(7,)])
    assert schedule_repo.count_source_extractions() == 7


# --- the route -----------------------------------------------------------------

@pytest.fixture
def client():
    from src.dependencies import get_current_user
    from src.security.auth import verify_auth
    from src.app import app

    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 1, "email": "admin@example.org", "role": "admin",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_route_reports_both_stocks(client):
    with patch("src.routes.admin.pools.db.pool_counts_by_tool", return_value={"quiz": 12}), \
         patch("src.routes.admin.pools.db.count_source_extractions", return_value=4):
        r = client.get("/admin/pools")
    assert r.status_code == 200
    assert r.json() == {"tools": {"quiz": 12}, "schedule": 4}


def test_the_route_clears_what_was_chosen(client):
    with patch("src.routes.admin.pools.db.clear_pool_for_tools", return_value=9) as clear_pool, \
         patch("src.routes.admin.pools.db.clear_source_extractions", return_value=4) as clear_sched:
        r = client.post("/admin/pools/clear", json={"tools": ["quiz"], "schedule": True})
    assert r.status_code == 200
    assert r.json() == {"items_deleted": 9, "extractions_deleted": 4}
    clear_pool.assert_called_once_with(["quiz"])
    clear_sched.assert_called_once_with()


def test_the_route_leaves_the_schedule_alone_when_it_was_not_chosen(client):
    with patch("src.routes.admin.pools.db.clear_pool_for_tools", return_value=9), \
         patch("src.routes.admin.pools.db.clear_source_extractions") as clear_sched:
        r = client.post("/admin/pools/clear", json={"tools": ["quiz"], "schedule": False})
    assert r.status_code == 200
    clear_sched.assert_not_called()


def test_the_route_refuses_an_empty_selection(client):
    """Without a checkbox nothing may happen, otherwise a misclick clears everything."""
    with patch("src.routes.admin.pools.db.clear_pool_for_tools") as clear_pool, \
         patch("src.routes.admin.pools.db.clear_source_extractions") as clear_sched:
        r = client.post("/admin/pools/clear", json={"tools": [], "schedule": False})
    assert r.status_code == 400
    clear_pool.assert_not_called()
    clear_sched.assert_not_called()


def test_the_route_refuses_an_unknown_tool(client):
    with patch("src.routes.admin.pools.db.clear_pool_for_tools") as clear_pool:
        r = client.post("/admin/pools/clear", json={"tools": ["gibtsnicht"], "schedule": False})
    assert r.status_code == 400
    clear_pool.assert_not_called()


def test_clearing_a_tool_starts_its_count_over(fake_pool_db):
    """An emptied pool with an old count would open at once and hand out the first set."""
    calls = fake_pool_db()
    pool_repo.clear_pool_for_tools(["quiz"])
    loeschung = next(
        (c[1], c[2]) for c in calls
        if c[0] == "execute" and "DELETE FROM aia_exercise_pool_runs" in c[1]
    )
    assert "tool = ANY" in loeschung[0]
    assert ["quiz"] in loeschung[1]
