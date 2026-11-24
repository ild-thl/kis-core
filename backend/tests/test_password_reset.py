"""Reset links: admin creates one, the password changes only when the person sets a new one."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.features.password_reset.service import can_get_reset_link, hash_token, may_create_link, status_of
from src.permissions import Permissions
from src.permissions_registry import PERM_SET_USERS_ALL

BCRYPT = "$2b$12$abcdefghijklmnopqrstuv"
ADMIN = {"user_id": 1, "email": "admin@th-luebeck.de", "role": "admin"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "admin@th-luebeck.de")
    from src.app import app
    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: dict(ADMIN)
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _konto(**ueberschrieben):
    konto = {"id": 7, "username": "max", "email": "max@x.de", "role": "user", "active": 1, "password_hash": BCRYPT}
    konto.update(ueberschrieben)
    return konto


def _eintrag(**ueberschrieben):
    e = {"id": 4, "user_id": 7, "used_at": None, "expires_at": datetime.now() + timedelta(days=1)}
    e.update(ueberschrieben)
    return e


def test_eligibility_rules():
    assert can_get_reset_link(_konto())
    assert not can_get_reset_link(_konto(password_hash=None))
    assert not can_get_reset_link(_konto(password_hash="{SSHA}xyz"))
    assert not can_get_reset_link(_konto(role="admin"))
    assert not can_get_reset_link(_konto(email="Admin@th-luebeck.de"), "admin@th-luebeck.de")


def test_status_of():
    jetzt = datetime.now()
    assert status_of(used_at=None, expires_at=jetzt + timedelta(days=1), now=jetzt) == "open"
    assert status_of(used_at=None, expires_at=jetzt, now=jetzt) == "expired"
    assert status_of(used_at=jetzt, expires_at=jetzt + timedelta(days=1), now=jetzt) == "used"


def test_creating_a_link_keeps_the_password_and_stores_only_the_hash(client):
    with patch("src.routes.admin.password_reset.database.get_user_by_id", return_value=_konto()), \
         patch("src.routes.admin.password_reset.repo.create_token") as anlegen, \
         patch("src.database.set_user_password") as setzen:
        r = client.post("/admin/users/7/reset-link")

    assert r.status_code == 200
    token = r.json()["token"]
    assert anlegen.call_args.kwargs["token_hash"] == hash_token(token)
    assert token not in str(anlegen.call_args)
    delta = anlegen.call_args.kwargs["expires_at"] - datetime.now()
    assert timedelta(days=13, hours=23) < delta <= timedelta(days=14)
    setzen.assert_not_called()


def test_an_admin_account_gets_no_link(client):
    with patch("src.routes.admin.password_reset.database.get_user_by_id", return_value=_konto(role="admin")), \
         patch("src.routes.admin.password_reset.repo.create_token") as anlegen:
        r = client.post("/admin/users/7/reset-link")
    assert r.status_code == 403
    anlegen.assert_not_called()


def test_opening_the_link_changes_nothing(client):
    with patch("src.routes.password_reset.repo.get_by_hash", return_value=_eintrag()), \
         patch("src.routes.password_reset.database.get_user_by_id", return_value=_konto()), \
         patch("src.routes.password_reset.database.set_user_password") as setzen:
        r = client.get("/password-reset/abc")
    assert r.status_code == 200
    assert r.json() == {"uid": "max"}
    setzen.assert_not_called()


def test_setting_a_new_password_changes_it_and_ends_sessions(client):
    with patch("src.routes.password_reset.repo.get_by_hash", return_value=_eintrag()), \
         patch("src.routes.password_reset.repo.mark_used", return_value=True), \
         patch("src.routes.password_reset.database.get_user_by_id", return_value=_konto()), \
         patch("src.routes.password_reset.database.set_user_password") as setzen, \
         patch("src.routes.password_reset.get_session_store") as store:
        r = client.post("/password-reset/abc", json={"password": "ein-neues-passwort"})
    assert r.status_code == 200
    assert setzen.call_args.args[0] == 7
    assert setzen.call_args.args[1].startswith("$2")
    store.return_value.destroy_for_users.assert_called_once_with([7])


@pytest.mark.parametrize("eintrag", [
    _eintrag(used_at=datetime.now()),
    _eintrag(expires_at=datetime.now() - timedelta(seconds=1)),
])
def test_used_or_expired_link_is_refused(client, eintrag):
    with patch("src.routes.password_reset.repo.get_by_hash", return_value=eintrag), \
         patch("src.routes.password_reset.database.get_user_by_id", return_value=_konto()), \
         patch("src.routes.password_reset.database.set_user_password") as setzen:
        r = client.post("/password-reset/abc", json={"password": "ein-neues-passwort"})
    assert r.status_code == 410
    setzen.assert_not_called()


def test_unknown_link_and_short_password(client):
    with patch("src.routes.password_reset.repo.get_by_hash", return_value=None):
        assert client.get("/password-reset/abc").status_code == 404
    with patch("src.routes.password_reset.repo.get_by_hash", return_value=_eintrag()), \
         patch("src.routes.password_reset.database.get_user_by_id", return_value=_konto()), \
         patch("src.routes.password_reset.database.set_user_password") as setzen:
        r = client.post("/password-reset/abc", json={"password": "kurz"})
    assert r.status_code == 400
    setzen.assert_not_called()


def _rechte(*keys):
    return Permissions(keys=frozenset(keys))


def test_a_target_who_manages_users_gets_no_link():
    with patch("src.features.password_reset.service.target_permissions", return_value=_rechte(PERM_SET_USERS_ALL)):
        assert not can_get_reset_link(_konto(role="custom", custom_role_id=3))


def test_creation_refuses_self_inactive_and_targets_with_more_rights():
    aktor = {"user_id": 1, "email": "a@x.de", "role": "staff"}
    assert not may_create_link(aktor, _konto(id=1))
    assert not may_create_link(aktor, _konto(active=0))
    with patch("src.features.password_reset.service.permissions_of", return_value=_rechte("a")), \
         patch("src.features.password_reset.service.target_permissions", return_value=_rechte("a", "b")):
        assert not may_create_link(aktor, _konto())
    with patch("src.features.password_reset.service.permissions_of", return_value=_rechte("a", "b")), \
         patch("src.features.password_reset.service.target_permissions", return_value=_rechte("a")):
        assert may_create_link(aktor, _konto())
