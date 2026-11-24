"""An expired test access gets neither a fresh session nor a running one."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

GESTERN = datetime.now() - timedelta(days=1)
MORGEN = datetime.now() + timedelta(days=1)


@pytest.fixture
def client(monkeypatch):

    from src.dependencies import get_settings
    from src.security.auth import verify_auth
    from src.app import app

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _anmelden(client, konto):
    """Logs in with the password check out of the way."""
    with patch("src.routes.auth.authenticate", return_value=konto), \
         patch("src.routes.auth.database.get_setting", return_value="false"), \
         patch("src.routes.auth.get_session_store") as store:
        store.return_value = MagicMock()
        store.return_value.create.return_value = "tok"
        antwort = client.post("/auth/login", json={
            "username": "max.mustermann", "password": "geheim123",
        })
        return antwort, store.return_value.create


def test_an_expired_test_access_cannot_log_in(client):
    konto = {"id": 42, "username": "max.mustermann",
             "display_name": "Max Mustermann", "email": "max.mustermann@demo.kis.local",
             "active": 1, "role": "staff", "custom_role_id": None,
             "access_expires_at": GESTERN}
    antwort, anlegen = _anmelden(client, konto)

    assert antwort.status_code == 403
    assert antwort.json()["detail"] == "access_expired"
    anlegen.assert_not_called()


def test_a_blocked_login_takes_the_dead_cookie_with_it(client):
    konto = {"id": 42, "username": "max.mustermann",
             "display_name": "Max Mustermann", "email": "max.mustermann@demo.kis.local",
             "active": 1, "role": "staff", "custom_role_id": None,
             "access_expires_at": GESTERN}
    antwort, _ = _anmelden(client, konto)

    keks = antwort.headers.get("set-cookie", "")
    assert keks.startswith("session=")
    assert "Max-Age=0" in keks


def test_a_running_test_access_carries_its_deadline_into_the_session(client):
    konto = {"id": 42, "username": "max.mustermann",
             "display_name": "Max Mustermann", "email": "max.mustermann@demo.kis.local",
             "active": 1, "role": "staff", "custom_role_id": None,
             "access_expires_at": MORGEN}
    antwort, anlegen = _anmelden(client, konto)

    assert antwort.status_code == 200
    assert anlegen.call_args.kwargs["data"]["access_expires_at"] == MORGEN.isoformat()


def test_a_normal_account_carries_no_deadline(client):
    konto = {"id": 5, "username": "chefin", "display_name": "Chefin",
             "email": "chefin@th-luebeck.de", "active": 1,
             "role": "admin", "custom_role_id": None, "access_expires_at": None}
    antwort, anlegen = _anmelden(client, konto)

    assert antwort.status_code == 200
    assert anlegen.call_args.kwargs["data"]["access_expires_at"] is None


class _Anfrage:
    """Just enough request for the gate."""

    def __init__(self, sitzung="tok"):
        self.url = SimpleNamespace(path="/aia/workspaces")
        self.cookies = {"session": sitzung} if sitzung else {}
        self.headers = {}


async def _torwaechter(sitzungsdaten, store=None):
    from src.security.auth import verify_auth

    store = store or MagicMock()
    store.get_data.return_value = sitzungsdaten
    with patch("src.security.auth.get_session_store", return_value=store), \
         patch("src.security.auth.get_settings", return_value=SimpleNamespace(is_local_mode=False)):
        return await verify_auth(_Anfrage())


@pytest.mark.asyncio
async def test_the_gate_lets_a_running_test_access_through():
    assert await _torwaechter({"user_id": 42, "access_expires_at": MORGEN.isoformat()}) is None


@pytest.mark.asyncio
async def test_the_gate_lets_a_normal_account_through():
    assert await _torwaechter({"user_id": 5, "access_expires_at": None}) is None


@pytest.mark.asyncio
async def test_the_gate_lets_an_old_session_without_the_key_through():
    assert await _torwaechter({"user_id": 5}) is None


@pytest.mark.asyncio
async def test_the_gate_throws_an_expired_test_access_out():
    with pytest.raises(HTTPException) as fehler:
        await _torwaechter({"user_id": 42, "access_expires_at": GESTERN.isoformat()})
    assert fehler.value.status_code == 403
    assert fehler.value.detail == "access_expired"


@pytest.mark.asyncio
async def test_the_gate_keeps_the_session_so_every_parallel_call_says_the_same():
    """Dropping it would answer the calls running next to this one with 401."""
    store = MagicMock()
    with pytest.raises(HTTPException):
        await _torwaechter({"user_id": 42, "access_expires_at": GESTERN.isoformat()}, store)
    store.destroy.assert_not_called()


@pytest.mark.asyncio
async def test_the_gate_takes_the_dead_cookie_with_it():
    with pytest.raises(HTTPException) as fehler:
        await _torwaechter({"user_id": 42, "access_expires_at": GESTERN.isoformat()})
    keks = (fehler.value.headers or {}).get("set-cookie", "")
    assert keks.startswith("session=")
    assert "Max-Age=0" in keks


@pytest.mark.asyncio
async def test_the_gate_lets_a_session_through_when_the_deadline_is_unparseable():
    assert await _torwaechter({"user_id": 42, "access_expires_at": "kaputt"}) is None


def test_login_lets_an_account_through_when_the_deadline_is_unparseable(client):
    konto = {"id": 42, "username": "max.mustermann", "display_name": "Max Mustermann",
             "email": "max.mustermann@demo.kis.local", "active": 1,
             "role": "staff", "custom_role_id": None, "access_expires_at": "kaputt"}
    antwort, anlegen = _anmelden(client, konto)

    assert antwort.status_code == 200
    assert anlegen.call_args.kwargs["data"]["access_expires_at"] is None


def _status(client, sitzungsdaten, konto):
    client.cookies.set("session", "tok")
    with patch("src.routes.auth.get_session_store") as store, \
         patch("src.routes.auth.database.get_user_by_id", return_value=konto):
        store.return_value = MagicMock()
        store.return_value.validate.return_value = True
        store.return_value.get_data.return_value = sitzungsdaten
        return client.get("/auth/status")


def test_status_reports_an_expired_access_as_not_authenticated(client):
    sitzungsdaten = {"user_id": 42, "email": "", "role": "staff", "custom_role_id": None}
    konto = {"id": 42, "role": "staff", "custom_role_id": None, "access_expires_at": GESTERN}
    antwort = _status(client, sitzungsdaten, konto)

    assert antwort.status_code == 200
    assert antwort.json() == {"authenticated": False, "reason": "access_expired"}


def test_status_leaves_the_session_alone(client):
    """Only the gate ends it, otherwise the next call answers 401 and loses the reason."""
    sitzungsdaten = {"user_id": 42, "email": "", "role": "staff", "custom_role_id": None}
    konto = {"id": 42, "role": "staff", "custom_role_id": None, "access_expires_at": GESTERN}
    client.cookies.set("session", "tok")
    with patch("src.routes.auth.get_session_store") as store, \
         patch("src.routes.auth.database.get_user_by_id", return_value=konto):
        store.return_value = MagicMock()
        store.return_value.validate.return_value = True
        store.return_value.get_data.return_value = sitzungsdaten
        antwort = client.get("/auth/status")
        store.return_value.destroy.assert_not_called()

    assert "set-cookie" not in antwort.headers


def test_status_names_no_reason_without_a_session(client):
    client.cookies.clear()
    antwort = client.get("/auth/status")

    assert antwort.json() == {"authenticated": False}


def test_status_still_reports_a_normal_account_as_authenticated(client):
    sitzungsdaten = {"user_id": 5, "email": "", "role": "admin", "custom_role_id": None}
    konto = {"id": 5, "role": "admin", "custom_role_id": None, "access_expires_at": None}
    antwort = _status(client, sitzungsdaten, konto)

    assert antwort.status_code == 200
    assert antwort.json()["authenticated"] is True
