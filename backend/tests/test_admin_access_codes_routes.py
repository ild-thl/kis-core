"""Access codes in the admin area: create, list, switch off, delete."""

import re
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.permissions_registry import PERM_SET_USERS_ALL

MORGEN = datetime.now() + timedelta(days=30)


@pytest.fixture
def client(monkeypatch):

    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth
    from src.app import app

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 1, "email": "admin@example.org", "role": "admin",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def limited_client(monkeypatch):
    """An admin whose custom role holds only user administration, nothing else."""

    from src import database
    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth
    from src.app import app

    get_settings.cache_clear()
    monkeypatch.setattr(
        database, "get_custom_role",
        lambda role_id: {"id": role_id, "name": "Nutzerverwaltung", "permissions": [PERM_SET_USERS_ALL]},
    )
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 2, "email": "eingeschraenkt@example.org",
        "role": "custom", "custom_role_id": 5,
    }
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def client_ohne_recht(monkeypatch):
    """A caller with no admin rights at all, to prove the gate itself holds."""

    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth
    from src.app import app

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 3, "email": "student@example.org", "role": "user",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_creating_a_code_returns_the_readable_code(client):
    with patch("src.routes.admin.access_codes.repo.create_code", return_value=7) as anlegen:
        r = client.post("/admin/access-codes", json={
            "label": "Kollegen August", "max_uses": 50,
            "valid_days": 30, "access_hours": 14, "kis_role": "staff",
        })

    assert r.status_code == 200
    assert re.fullmatch(r"KIS-[A-Z2-9]{4}-[A-Z2-9]{4}", r.json()["code"])
    assert anlegen.call_args.kwargs["max_uses"] == 50
    assert anlegen.call_args.kwargs["access_hours"] == 14
    assert anlegen.call_args.kwargs["created_by"] == 1


def test_creating_a_code_with_unlimited_access(client):
    with patch("src.routes.admin.access_codes.repo.create_code", return_value=7) as anlegen:
        r = client.post("/admin/access-codes", json={
            "label": "Kollegen August", "max_uses": 50,
            "valid_days": 30, "access_hours": None, "kis_role": "staff",
        })

    assert r.status_code == 200
    assert anlegen.call_args.kwargs["access_hours"] is None


def test_creating_a_code_with_access_hours_above_the_cap_is_refused(client):
    with patch("src.routes.admin.access_codes.repo.create_code") as anlegen:
        r = client.post("/admin/access-codes", json={
            "label": "Kollegen August", "max_uses": 50,
            "valid_days": 30, "access_hours": 721, "kis_role": "staff",
        })

    assert r.status_code in (400, 422)
    anlegen.assert_not_called()


def test_creating_a_code_with_a_twelve_hour_lifetime_for_an_event(client):
    with patch("src.routes.admin.access_codes.repo.create_code", return_value=7) as anlegen:
        r = client.post("/admin/access-codes", json={
            "label": "Tag der Lehre", "max_uses": 500,
            "valid_days": 1, "access_hours": 12, "kis_role": "user",
            "show_credentials": False,
        })

    assert r.status_code == 200
    assert anlegen.call_args.kwargs["access_hours"] == 12
    assert anlegen.call_args.kwargs["max_uses"] == 500
    assert anlegen.call_args.kwargs["show_credentials"] is False


def test_creating_a_code_defaults_to_showing_credentials(client):
    with patch("src.routes.admin.access_codes.repo.create_code", return_value=7) as anlegen:
        r = client.post("/admin/access-codes", json={
            "label": "Kollegen August", "max_uses": 50,
            "valid_days": 30, "access_hours": 14, "kis_role": "staff",
        })

    assert r.status_code == 200
    assert anlegen.call_args.kwargs["show_credentials"] is True


def test_creating_a_code_with_the_evaluation_switch(client):
    with patch("src.routes.admin.access_codes.repo.create_code", return_value=7) as anlegen:
        r = client.post("/admin/access-codes", json={
            "label": "Tag der Lehre", "max_uses": 500,
            "valid_days": 1, "access_hours": 12, "kis_role": "user",
            "show_evaluation": True,
        })

    assert r.status_code == 200
    assert anlegen.call_args.kwargs["show_evaluation"] is True


def test_creating_a_code_leaves_the_evaluation_off_by_default(client):
    with patch("src.routes.admin.access_codes.repo.create_code", return_value=7) as anlegen:
        r = client.post("/admin/access-codes", json={
            "label": "Kollegen August", "max_uses": 50,
            "valid_days": 30, "access_hours": 14, "kis_role": "staff",
        })

    assert r.status_code == 200
    assert anlegen.call_args.kwargs["show_evaluation"] is False


def test_creating_a_code_with_500_seats_for_a_big_event_is_allowed(client):
    with patch("src.routes.admin.access_codes.repo.create_code", return_value=7) as anlegen:
        r = client.post("/admin/access-codes", json={
            "label": "Tag der Lehre", "max_uses": 500,
            "valid_days": 1, "access_hours": 12, "kis_role": "user",
        })

    assert r.status_code == 200
    assert anlegen.call_args.kwargs["max_uses"] == 500


def test_creating_a_code_with_more_than_500_seats_is_refused(client):
    with patch("src.routes.admin.access_codes.repo.create_code") as anlegen:
        r = client.post("/admin/access-codes", json={
            "label": "Kollegen August", "max_uses": 501,
            "valid_days": 30, "access_hours": 14, "kis_role": "staff",
        })

    assert r.status_code in (400, 422)
    anlegen.assert_not_called()


def test_creating_a_code_without_a_name_is_refused(client):
    with patch("src.routes.admin.access_codes.repo.create_code") as anlegen:
        r = client.post("/admin/access-codes", json={
            "label": "   ", "max_uses": 50, "valid_days": 30,
            "access_hours": 14, "kis_role": "staff",
        })

    assert r.status_code in (400, 422)
    anlegen.assert_not_called()


def test_a_custom_role_has_to_exist(client):
    with patch("src.routes.admin.access_codes.database.get_custom_role", return_value=None), \
         patch("src.routes.admin.access_codes.repo.create_code") as anlegen:
        r = client.post("/admin/access-codes", json={
            "label": "Sprachenzentrum", "max_uses": 10, "valid_days": 30,
            "access_hours": 21, "kis_role": "custom", "custom_role_id": 99,
        })

    assert r.status_code == 400
    anlegen.assert_not_called()


def test_the_list_carries_the_state_of_every_code(client):
    eintraege = [
        {"id": 1, "code": "KIS-AAAA-BBBB", "label": "A", "role": "staff",
         "custom_role_id": None, "max_uses": 50, "used_count": 3,
         "valid_until": MORGEN, "access_hours": 14, "show_credentials": True,
         "show_evaluation": True, "active": True,
         "created_at": MORGEN, "created_by": 1},
        {"id": 2, "code": "KIS-CCCC-DDDD", "label": "B", "role": "user",
         "custom_role_id": None, "max_uses": 5, "used_count": 5,
         "valid_until": MORGEN, "access_hours": 14, "show_credentials": True,
         "show_evaluation": False, "active": True,
         "created_at": MORGEN, "created_by": 1},
        {"id": 3, "code": "KIS-EEEE-FFFF", "label": "C", "role": "user",
         "custom_role_id": None, "max_uses": 5, "used_count": 0,
         "valid_until": MORGEN, "access_hours": 14, "show_credentials": True,
         "show_evaluation": False, "active": False,
         "created_at": MORGEN, "created_by": 1},
    ]
    with patch("src.routes.admin.access_codes.repo.list_codes", return_value=eintraege):
        r = client.get("/admin/access-codes")

    zustaende = [e["status"] for e in r.json()["codes"]]
    assert zustaende == ["active", "full", "disabled"]
    assert [e["show_evaluation"] for e in r.json()["codes"]] == [True, False, False], \
        "der Dialog stellt den Haken danach wieder her"


def test_switching_a_code_off(client):
    with patch("src.routes.admin.access_codes.repo.set_active", return_value=True) as um:
        r = client.patch("/admin/access-codes/7", json={"active": False})

    assert r.status_code == 200
    um.assert_called_once_with(7, False)


def test_switching_an_unknown_code_reports_not_found(client):
    with patch("src.routes.admin.access_codes.repo.set_active", return_value=False):
        r = client.patch("/admin/access-codes/999", json={"active": False})
    assert r.status_code == 404


def test_editing_a_code_updates_every_field_but_the_code(client):
    bestehend = {"id": 7, "code": "KIS-AAAA-BBBB", "label": "Alt", "role": "user",
                 "custom_role_id": None, "max_uses": 50, "used_count": 3,
                 "valid_until": MORGEN, "access_hours": 14, "active": True}
    with patch("src.routes.admin.access_codes.repo.get_code_by_id", return_value=bestehend), \
         patch("src.routes.admin.access_codes.repo.update_code", return_value=True) as bearbeiten:
        r = client.patch("/admin/access-codes/7", json={
            "label": "Kollegen September", "max_uses": 25,
            "valid_days": 14, "access_hours": 21, "kis_role": "staff",
            "show_credentials": False,
        })

    assert r.status_code == 200
    assert bearbeiten.call_args.args[0] == 7
    assert bearbeiten.call_args.kwargs["label"] == "Kollegen September"
    assert bearbeiten.call_args.kwargs["max_uses"] == 25
    assert bearbeiten.call_args.kwargs["access_hours"] == 21
    assert bearbeiten.call_args.kwargs["role"] == "staff"
    assert bearbeiten.call_args.kwargs["show_credentials"] is False


def test_editing_without_show_credentials_leaves_it_switched_on(client):
    bestehend = {"id": 7, "code": "KIS-AAAA-BBBB", "label": "Alt", "role": "user",
                 "custom_role_id": None, "max_uses": 50, "used_count": 3,
                 "valid_until": MORGEN, "access_hours": 14, "active": True}
    with patch("src.routes.admin.access_codes.repo.get_code_by_id", return_value=bestehend), \
         patch("src.routes.admin.access_codes.repo.update_code", return_value=True) as bearbeiten:
        r = client.patch("/admin/access-codes/7", json={
            "label": "Kollegen September", "max_uses": 25,
            "valid_days": 14, "access_hours": 21, "kis_role": "staff",
        })

    assert r.status_code == 200
    assert bearbeiten.call_args.kwargs["show_credentials"] is True


def test_editing_switches_the_evaluation_on_afterwards(client):
    """The switch was forgotten while creating the code, the edit has to fix that."""
    bestehend = {"id": 7, "code": "KIS-AAAA-BBBB", "label": "Alt", "role": "user",
                 "custom_role_id": None, "max_uses": 50, "used_count": 3,
                 "valid_until": MORGEN, "access_hours": 14, "active": True}
    with patch("src.routes.admin.access_codes.repo.get_code_by_id", return_value=bestehend), \
         patch("src.routes.admin.access_codes.repo.update_code", return_value=True) as bearbeiten:
        r = client.patch("/admin/access-codes/7", json={
            "label": "Tag der Lehre", "max_uses": 25,
            "valid_days": 14, "access_hours": 12, "kis_role": "user",
            "show_evaluation": True,
        })

    assert r.status_code == 200
    assert bearbeiten.call_args.kwargs["show_evaluation"] is True


def test_editing_without_the_evaluation_field_leaves_it_off(client):
    bestehend = {"id": 7, "code": "KIS-AAAA-BBBB", "label": "Alt", "role": "user",
                 "custom_role_id": None, "max_uses": 50, "used_count": 3,
                 "valid_until": MORGEN, "access_hours": 14, "active": True}
    with patch("src.routes.admin.access_codes.repo.get_code_by_id", return_value=bestehend), \
         patch("src.routes.admin.access_codes.repo.update_code", return_value=True) as bearbeiten:
        r = client.patch("/admin/access-codes/7", json={
            "label": "Kollegen September", "max_uses": 25,
            "valid_days": 14, "access_hours": 21, "kis_role": "staff",
        })

    assert r.status_code == 200
    assert bearbeiten.call_args.kwargs["show_evaluation"] is False


def test_editing_an_unknown_code_reports_not_found(client):
    with patch("src.routes.admin.access_codes.repo.get_code_by_id", return_value=None), \
         patch("src.routes.admin.access_codes.repo.update_code") as bearbeiten:
        r = client.patch("/admin/access-codes/999", json={
            "label": "Kollegen September", "max_uses": 25,
            "valid_days": 14, "access_hours": 21, "kis_role": "staff",
        })

    assert r.status_code == 404
    bearbeiten.assert_not_called()


def test_editing_to_reduce_max_uses_below_used_count_is_refused(client):
    bestehend = {"id": 7, "code": "KIS-AAAA-BBBB", "label": "Alt", "role": "user",
                 "custom_role_id": None, "max_uses": 50, "used_count": 10,
                 "valid_until": MORGEN, "access_hours": 14, "active": True}
    with patch("src.routes.admin.access_codes.repo.get_code_by_id", return_value=bestehend), \
         patch("src.routes.admin.access_codes.repo.update_code", return_value=False) as bearbeiten:
        r = client.patch("/admin/access-codes/7", json={
            "label": "Alt", "max_uses": 5,
            "valid_days": 14, "access_hours": 21, "kis_role": "staff",
        })

    assert r.status_code == 400
    bearbeiten.assert_called_once()


def test_editing_to_a_role_beyond_the_admins_own_permissions_is_refused(limited_client):
    bestehend = {"id": 7, "code": "KIS-AAAA-BBBB", "label": "Alt", "role": "user",
                 "custom_role_id": None, "max_uses": 50, "used_count": 3,
                 "valid_until": MORGEN, "access_hours": 14, "active": True}
    with patch("src.routes.admin.access_codes.repo.get_code_by_id", return_value=bestehend), \
         patch("src.routes.admin.access_codes.repo.update_code") as bearbeiten:
        r = limited_client.patch("/admin/access-codes/7", json={
            "label": "Zuviel", "max_uses": 5,
            "valid_days": 30, "access_hours": 14, "kis_role": "staff",
        })

    assert r.status_code == 403
    bearbeiten.assert_not_called()


def test_editing_needs_a_custom_role_that_exists(client):
    bestehend = {"id": 7, "code": "KIS-AAAA-BBBB", "label": "Alt", "role": "user",
                 "custom_role_id": None, "max_uses": 50, "used_count": 3,
                 "valid_until": MORGEN, "access_hours": 14, "active": True}
    with patch("src.routes.admin.access_codes.repo.get_code_by_id", return_value=bestehend), \
         patch("src.routes.admin.access_codes.database.get_custom_role", return_value=None), \
         patch("src.routes.admin.access_codes.repo.update_code") as bearbeiten:
        r = client.patch("/admin/access-codes/7", json={
            "label": "Sprachenzentrum", "max_uses": 10, "valid_days": 30,
            "access_hours": 21, "kis_role": "custom", "custom_role_id": 99,
        })

    assert r.status_code == 400
    bearbeiten.assert_not_called()


def test_editing_without_all_the_edit_fields_together_is_refused(client):
    with patch("src.routes.admin.access_codes.repo.get_code_by_id") as holen, \
         patch("src.routes.admin.access_codes.repo.update_code") as bearbeiten:
        r = client.patch("/admin/access-codes/7", json={"max_uses": 25})

    assert r.status_code == 422
    holen.assert_not_called()
    bearbeiten.assert_not_called()


def test_switching_a_code_off_still_needs_no_other_field(client):
    with patch("src.routes.admin.access_codes.repo.get_code_by_id") as holen, \
         patch("src.routes.admin.access_codes.repo.set_active", return_value=True) as um:
        r = client.patch("/admin/access-codes/7", json={"active": False})

    assert r.status_code == 200
    um.assert_called_once_with(7, False)
    holen.assert_not_called()


def test_deleting_a_code(client):
    with patch("src.routes.admin.access_codes.repo.delete_code", return_value=True) as weg:
        r = client.delete("/admin/access-codes/7")

    assert r.status_code == 200
    weg.assert_called_once_with(7)


def test_deleting_an_unknown_code_reports_not_found(client):
    with patch("src.routes.admin.access_codes.repo.delete_code", return_value=False):
        r = client.delete("/admin/access-codes/999")
    assert r.status_code == 404


def test_a_role_beyond_the_admins_own_permissions_is_refused(limited_client):
    with patch("src.routes.admin.access_codes.repo.create_code") as anlegen:
        r = limited_client.post("/admin/access-codes", json={
            "label": "Zuviel", "max_uses": 5, "valid_days": 30,
            "access_hours": 14, "kis_role": "staff",
        })

    assert r.status_code == 403
    anlegen.assert_not_called()


def test_without_the_permission_the_list_stays_shut(client_ohne_recht):
    r = client_ohne_recht.get("/admin/access-codes")
    assert r.status_code == 403


GESTERN = datetime.now() - timedelta(days=1)


def test_the_user_list_carries_the_state_of_every_account(client):
    konten = [
        {"id": 1, "username": "abc12345", "created_at": MORGEN,
         "access_expires_at": MORGEN, "active": True},
        {"id": 2, "username": "def67890", "created_at": MORGEN,
         "access_expires_at": GESTERN, "active": True},
        {"id": 3, "username": "ghi13579", "created_at": MORGEN,
         "access_expires_at": MORGEN, "active": False},
        {"id": 4, "username": "jkl24680", "created_at": MORGEN,
         "access_expires_at": None, "active": True},
    ]
    with patch("src.routes.admin.access_codes.repo.list_users_for_code", return_value=konten):
        r = client.get("/admin/access-codes/7/users")

    assert r.status_code == 200
    zustaende = [u["status"] for u in r.json()["users"]]
    assert zustaende == ["active", "expired", "disabled", "active"], \
        "eine leere Frist heisst unbegrenzt gueltig, nicht abgelaufen"


def test_resetting_a_password_writes_a_hash_of_the_new_one(client):
    from src.features.accounts.passwords import verify_password

    konto = {"id": 42, "username": "abc12345", "access_code_id": 7}
    with patch("src.routes.admin.access_codes.database.get_user_by_id", return_value=konto), \
         patch("src.routes.admin.access_codes.database.set_user_password") as setzen:
        r = client.post("/admin/access-codes/users/42/password")

    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "abc12345"
    assert body["password"]
    assert setzen.call_args.args[0] == 42
    assert verify_password(body["password"], setzen.call_args.args[1]) is True


def test_resetting_a_password_for_an_account_without_a_code_is_refused(client):
    konto = {"id": 5, "username": "staffuser", "access_code_id": None}
    with patch("src.routes.admin.access_codes.database.get_user_by_id", return_value=konto), \
         patch("src.routes.admin.access_codes.database.set_user_password") as setzen:
        r = client.post("/admin/access-codes/users/5/password")

    assert r.status_code == 403
    setzen.assert_not_called()


def test_the_activity_route_returns_modules_and_messages(client):
    konto = {"id": 42, "username": "abc12345", "access_code_id": 7}
    module = [{"workspace_id": 1, "title": "Deutsch A1", "relation": "owner", "since": MORGEN}]
    nachrichten = [{
        "role": "user", "content": "Was bedeutet das?", "created_at": MORGEN,
        "failed": False, "aborted": False, "workspace_title": "Deutsch A1",
    }]
    with patch("src.routes.admin.access_codes.database.get_user_by_id", return_value=konto), \
         patch("src.routes.admin.access_codes.repo.list_workspaces_for_user", return_value=module) as ws, \
         patch("src.routes.admin.access_codes.repo.list_messages_for_user", return_value=nachrichten) as msg:
        r = client.get("/admin/access-codes/users/42/activity")

    assert r.status_code == 200
    body = r.json()
    assert body["workspaces"][0]["relation"] == "owner"
    assert body["messages"][0]["role"] == "user"
    ws.assert_called_once_with(42)
    msg.assert_called_once_with(42)


def test_the_activity_route_refuses_an_account_without_a_code(client):
    konto = {"id": 5, "username": "staffuser", "access_code_id": None}
    with patch("src.routes.admin.access_codes.database.get_user_by_id", return_value=konto), \
         patch("src.routes.admin.access_codes.repo.list_workspaces_for_user") as ws, \
         patch("src.routes.admin.access_codes.repo.list_messages_for_user") as msg:
        r = client.get("/admin/access-codes/users/5/activity")

    assert r.status_code == 403
    ws.assert_not_called()
    msg.assert_not_called()


def test_the_activity_route_refuses_an_unknown_account(client):
    with patch("src.routes.admin.access_codes.database.get_user_by_id", return_value=None), \
         patch("src.routes.admin.access_codes.repo.list_workspaces_for_user") as ws, \
         patch("src.routes.admin.access_codes.repo.list_messages_for_user") as msg:
        r = client.get("/admin/access-codes/users/999/activity")

    assert r.status_code == 403
    ws.assert_not_called()
    msg.assert_not_called()


class _FakeActivityCursor:
    """Captures every execute() call so the SQL LIMIT can be checked."""

    def __init__(self):
        self.calls: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def fetchall(self):
        return []


class _FakeActivityConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self, **kwargs):
        return self._cursor


def test_the_message_cap_is_fifty(monkeypatch):
    from src.features.access_codes import repository as repo

    cursor = _FakeActivityCursor()
    monkeypatch.setattr(repo, "get_connection", lambda: _FakeActivityConn(cursor))

    repo.list_messages_for_user(42)

    sql, params = cursor.calls[0]
    assert "LIMIT %s" in sql
    assert params[-1] == 50, "die Obergrenze muss bei 50 liegen, sonst waechst die Abfrage unbegrenzt"


def test_the_user_list_says_when_every_account_will_be_deleted(client):
    """The admin needs to see how long the evaluation data is still there."""
    konten = [
        {"id": 1, "username": "abc12345", "created_at": MORGEN,
         "access_expires_at": datetime(2026, 9, 1, 12, 0), "active": False},
        {"id": 2, "username": "def67890", "created_at": MORGEN,
         "access_expires_at": None, "active": True},
    ]
    with patch("src.routes.admin.access_codes.repo.list_users_for_code", return_value=konten), \
         patch("src.features.access_codes.retention.get_setting", return_value="30"):
        r = client.get("/admin/access-codes/7/users")

    assert r.status_code == 200
    termine = [u["delete_at"] for u in r.json()["users"]]
    assert termine == [datetime(2026, 10, 1, 12, 0).isoformat(), None]


def test_the_user_list_promises_no_deletion_while_the_sweep_is_off(client):
    konten = [
        {"id": 1, "username": "abc12345", "created_at": MORGEN,
         "access_expires_at": datetime(2026, 9, 1, 12, 0), "active": False},
    ]
    with patch("src.routes.admin.access_codes.repo.list_users_for_code", return_value=konten), \
         patch("src.features.access_codes.retention.get_setting", return_value="0"):
        r = client.get("/admin/access-codes/7/users")

    assert r.json()["users"][0]["delete_at"] is None


def test_creating_a_code_stores_the_chosen_workspaces(client):
    with patch("src.routes.admin.access_codes.repo.create_code", return_value=7), \
         patch("src.routes.admin.access_codes.repo.set_code_workspaces") as zuordnen:
        r = client.post("/admin/access-codes", json={
            "label": "Seminar Recht", "max_uses": 30, "valid_days": 14,
            "access_hours": None, "kis_role": "user", "workspace_ids": [11, 12],
        })

    assert r.status_code == 200
    zuordnen.assert_called_once_with(7, [11, 12])


def test_creating_a_code_without_workspaces_writes_none(client):
    with patch("src.routes.admin.access_codes.repo.create_code", return_value=7), \
         patch("src.routes.admin.access_codes.repo.set_code_workspaces") as zuordnen:
        r = client.post("/admin/access-codes", json={
            "label": "Kollegen August", "max_uses": 50,
            "valid_days": 30, "access_hours": 14, "kis_role": "staff",
        })

    assert r.status_code == 200
    zuordnen.assert_not_called()


def test_editing_the_workspaces_also_enrolls_earlier_accounts(client):
    with patch("src.routes.admin.access_codes.repo.get_code_by_id", return_value={"id": 7}), \
         patch("src.routes.admin.access_codes.repo.update_code", return_value=True), \
         patch("src.routes.admin.access_codes.repo.set_code_workspaces") as zuordnen, \
         patch("src.routes.admin.access_codes.repo.list_user_ids_for_code", return_value=[42, 43]), \
         patch("src.routes.admin.access_codes.repo.enroll_into_code_workspaces", return_value=2) as einschreiben:
        r = client.patch("/admin/access-codes/7", json={
            "label": "Seminar Recht", "max_uses": 30, "valid_days": 14,
            "access_hours": None, "kis_role": "user", "workspace_ids": [11],
        })

    assert r.status_code == 200
    zuordnen.assert_called_once_with(7, [11])
    einschreiben.assert_called_once_with(7, [42, 43])


def test_switching_a_code_off_leaves_its_workspaces_alone(client):
    with patch("src.routes.admin.access_codes.repo.set_active", return_value=True), \
         patch("src.routes.admin.access_codes.repo.set_code_workspaces") as zuordnen:
        r = client.patch("/admin/access-codes/7", json={"active": False})

    assert r.status_code == 200
    zuordnen.assert_not_called()


def test_the_list_carries_each_codes_workspaces(client):
    eintrag = {
        "id": 7, "code": "KIS-4K2P-7RXM", "label": "Seminar", "role": "user",
        "custom_role_id": None, "max_uses": 30, "used_count": 0, "valid_until": MORGEN,
        "access_hours": None, "show_credentials": True, "show_evaluation": False,
        "active": True, "created_at": datetime.now(),
    }
    arbeitsbereich = {"id": 11, "title": "Recht", "owner_id": 5, "owner_name": "Erika"}
    with patch("src.routes.admin.access_codes.repo.list_codes", return_value=[eintrag]), \
         patch("src.routes.admin.access_codes.repo.workspaces_by_code", return_value={7: [arbeitsbereich]}):
        r = client.get("/admin/access-codes")

    assert r.status_code == 200
    assert r.json()["codes"][0]["workspaces"] == [arbeitsbereich]


def test_the_workspace_owners_are_searched_in_the_database(client):
    besitzer = [{"user_id": 5, "name": "Erika", "username": "erika", "role": "staff",
                 "workspaces": [{"id": 11, "title": "Recht"}]}]
    with patch("src.routes.admin.access_codes.repo.search_workspace_owners", return_value=besitzer) as suche, \
         patch("src.routes.admin.access_codes.repo.custom_role_ids_with", return_value=[4]):
        r = client.get("/admin/access-codes/workspace-owners", params={"q": " eri "})

    assert r.status_code == 200
    assert r.json() == {"owners": besitzer}
    argumente = suche.call_args.kwargs
    assert argumente["query"] == "eri"
    assert "staff" in argumente["system_roles"] and "user" not in argumente["system_roles"]
    assert argumente["custom_role_ids"] == [4]
    assert argumente["limit"] == 20


def test_the_workspace_owners_can_be_fetched_by_id_for_editing(client):
    with patch("src.routes.admin.access_codes.repo.search_workspace_owners", return_value=[]) as suche, \
         patch("src.routes.admin.access_codes.repo.custom_role_ids_with", return_value=[]):
        client.get("/admin/access-codes/workspace-owners?user_ids=5&user_ids=6")

    assert suche.call_args.kwargs["user_ids"] == [5, 6]


def test_without_search_nothing_is_loaded(client):
    with patch("src.routes.admin.access_codes.repo.search_workspace_owners") as suche:
        r = client.get("/admin/access-codes/workspace-owners")

    assert r.json() == {"owners": []}
    suche.assert_not_called()


def test_the_workspace_owners_stay_closed_without_the_right(client_ohne_recht):
    with patch("src.routes.admin.access_codes.repo.search_workspace_owners") as liste:
        r = client_ohne_recht.get("/admin/access-codes/workspace-owners", params={"q": "a"})

    assert r.status_code == 403
    liste.assert_not_called()
