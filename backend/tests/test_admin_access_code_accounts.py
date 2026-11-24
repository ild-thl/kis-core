"""Locking, deleting and listing the accounts that access codes created."""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

R = "src.routes.admin.access_codes"


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
def client_ohne_recht(monkeypatch):

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


def test_bulk_lock_for_one_code_locks_only_its_accounts(client):
    with patch(f"{R}.repo.get_code_by_id", return_value={"id": 4}), \
         patch(f"{R}.repo.list_user_ids_for_code", return_value=[7, 8]), \
         patch(f"{R}.lock_accounts", return_value=2) as sperren:
        r = client.post("/admin/access-codes/users/bulk", json={"action": "lock", "code_id": 4})

    assert r.status_code == 200
    assert r.json()["count"] == 2
    sperren.assert_called_once_with([7, 8])


def test_bulk_delete_takes_the_accounts_of_the_code(client):
    with patch(f"{R}.repo.get_code_by_id", return_value={"id": 4}), \
         patch(f"{R}.repo.list_user_ids_for_code", return_value=[7, 8, 9]), \
         patch(f"{R}.delete_accounts", return_value=3) as loeschen:
        r = client.post("/admin/access-codes/users/bulk", json={"action": "delete", "code_id": 4})

    assert r.status_code == 200
    loeschen.assert_called_once_with([7, 8, 9])


def test_bulk_without_a_code_is_refused(client):
    with patch(f"{R}.delete_accounts") as loeschen:
        r = client.post("/admin/access-codes/users/bulk", json={"action": "delete"})

    assert r.status_code == 422
    loeschen.assert_not_called()


def test_bulk_for_an_unknown_code_is_404(client):
    with patch(f"{R}.repo.get_code_by_id", return_value=None), \
         patch(f"{R}.lock_accounts") as sperren:
        r = client.post("/admin/access-codes/users/bulk", json={"action": "lock", "code_id": 99})

    assert r.status_code == 404
    sperren.assert_not_called()


def test_bulk_with_an_unknown_action_is_refused(client):
    r = client.post("/admin/access-codes/users/bulk", json={"action": "wipe", "code_id": 4})
    assert r.status_code == 422


def test_locking_one_account_ends_its_login(client):
    with patch(f"{R}.database.get_user_by_id", return_value={"id": 7, "access_code_id": 4}), \
         patch(f"{R}.lock_accounts", return_value=1) as sperren:
        r = client.patch("/admin/access-codes/users/7", json={"active": False})

    assert r.status_code == 200
    sperren.assert_called_once_with([7])


def test_unlocking_one_account_switches_it_on(client):
    with patch(f"{R}.database.get_user_by_id", return_value={"id": 7, "access_code_id": 4}), \
         patch(f"{R}.repo.set_users_active", return_value=[7]) as schalten:
        r = client.patch("/admin/access-codes/users/7", json={"active": True})

    assert r.status_code == 200
    schalten.assert_called_once_with([7], True)


def test_a_real_account_can_neither_be_locked_nor_deleted_here(client):
    with patch(f"{R}.database.get_user_by_id", return_value={"id": 5, "access_code_id": None}), \
         patch(f"{R}.lock_accounts") as sperren, \
         patch(f"{R}.delete_accounts") as loeschen:
        gesperrt = client.patch("/admin/access-codes/users/5", json={"active": False})
        geloescht = client.delete("/admin/access-codes/users/5")

    assert gesperrt.status_code == 403
    assert geloescht.status_code == 403
    sperren.assert_not_called()
    loeschen.assert_not_called()


def test_deleting_one_account(client):
    with patch(f"{R}.database.get_user_by_id", return_value={"id": 7, "access_code_id": 4}), \
         patch(f"{R}.delete_accounts", return_value=1) as loeschen:
        r = client.delete("/admin/access-codes/users/7")

    assert r.status_code == 200
    loeschen.assert_called_once_with([7])


def test_without_the_right_nothing_is_locked(client_ohne_recht):
    with patch(f"{R}.lock_accounts") as sperren:
        r = client_ohne_recht.post("/admin/access-codes/users/bulk", json={"action": "lock", "code_id": 4})

    assert r.status_code == 403
    sperren.assert_not_called()


def test_lock_accounts_ends_the_sessions_of_the_locked_accounts():
    from src.features.access_codes import accounts

    class _Store:
        beendet = None

        def destroy_for_users(self, ids):
            _Store.beendet = ids

    with patch.object(accounts.repo, "set_users_active", return_value=[7]), \
         patch.object(accounts, "get_session_store", return_value=_Store()):
        assert accounts.lock_accounts([7, 8]) == 1

    assert _Store.beendet == [7]


def test_destroy_for_users_removes_only_matching_sessions():
    from src.services.session import SessionStore

    class _Redis:
        def __init__(self):
            self.daten = {
                b"kis:session:a": json.dumps({"user_id": 7}),
                b"kis:session:b": json.dumps({"user_id": 8}),
                b"kis:session:c": "kaputt",
            }

        def scan_iter(self, match, count):
            return list(self.daten)

        def get(self, key):
            return self.daten.get(key)

        def delete(self, key):
            self.daten.pop(key, None)

    store = SessionStore(secret="x")
    store._client = _Redis()
    assert store.destroy_for_users([7]) == 1
    assert list(store._client.daten) == [b"kis:session:b", b"kis:session:c"]
