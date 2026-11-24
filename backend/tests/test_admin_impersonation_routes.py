"""Logging in as somebody else: the gates, the record and the way back."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.permissions_registry import (
    PERM_SET_STATS_USERS,
    PERM_SET_USERS_ALL,
    PERM_SET_USERS_IMPERSONATE,
)

ADMIN = {"user_id": 1, "username": "chef", "display_name": "Chefin",
         "email": "admin@example.org", "role": "admin", "custom_role_id": None}


class FakeStore:
    """Session store in a dictionary, enough for cookie and record."""

    def __init__(self, vorhanden: dict[str, dict] | None = None):
        self.data: dict[str, dict] = dict(vorhanden or {})
        self.zaehler = 0

    def create(self, data=None) -> str:
        self.zaehler += 1
        token = f"token-{self.zaehler}"
        self.data[token] = dict(data or {})
        return token

    def get_data(self, token):
        return self.data.get(token)

    def validate(self, token) -> bool:
        return token in self.data

    def destroy(self, token) -> None:
        self.data.pop(token, None)


def _user(**felder) -> dict:
    basis = {
        "id": 7, "username": "anna", "display_name": "Anna Beispiel",
        "email": "anna@example.org", "role": "user", "custom_role_id": None,
        "active": 1, "access_expires_at": None,
    }
    basis.update(felder)
    return basis


@pytest.fixture
def umgebung(monkeypatch):
    """App with a fake session store, a fake record and a settable target."""
    monkeypatch.setenv("ADMIN_EMAIL", "chef@example.org")

    from src import database
    from src.app import app
    from src.dependencies import get_current_user, get_settings
    from src.features.impersonation import repository as repo
    from src.routes.admin import impersonation as route
    from src.security.auth import verify_auth

    get_settings.cache_clear()
    store = FakeStore({"eigene": dict(ADMIN)})
    eintraege: list[dict] = []
    ziel = {"row": _user()}

    monkeypatch.setattr(route, "get_session_store", lambda: store)
    monkeypatch.setattr(database, "get_user_by_id", lambda uid: ziel["row"])
    monkeypatch.setattr(database, "get_custom_role", lambda rid: None)

    def _start(**kw):
        eintraege.append({**kw, "ended_reason": None})
        return 42

    monkeypatch.setattr(repo, "start_entry", _start)
    monkeypatch.setattr(
        repo, "end_entry",
        lambda entry_id, reason: eintraege.append({"ended": entry_id, "reason": reason}),
    )
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: dict(ADMIN)

    client = TestClient(app)
    yield {"client": client, "store": store, "log": eintraege, "ziel": ziel,
           "app": app, "dep": get_current_user}
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _als(umgebung, session: dict) -> None:
    """Swaps the calling session for the next request."""
    umgebung["app"].dependency_overrides[umgebung["dep"]] = lambda: dict(session)


def _post(umgebung, pfad: str, cookie: str = "eigene"):
    """One request with exactly one session cookie, the jar stays empty."""
    umgebung["client"].cookies.clear()
    return umgebung["client"].post(pfad, cookies={"session": cookie})


GELIEHEN = {
    "user_id": 7, "username": "anna", "role": "user", "custom_role_id": None,
    "impersonator": {"user_id": 1, "username": "chef", "display_name": "Chefin", "log_id": 42},
    "impersonator_token": "eigene",
}


# ─── Die Wachen ──────────────────────────────────────────────────────────────

def test_ohne_recht_kein_zutritt(umgebung):
    _als(umgebung, {"user_id": 2, "username": "lisa", "role": "staff",
                    "email": "lisa@example.org", "custom_role_id": None})
    antwort = _post(umgebung, "/admin/users/7/impersonate")
    assert antwort.status_code == 403


def test_unbekanntes_konto_ist_404(umgebung):
    umgebung["ziel"]["row"] = None
    antwort = _post(umgebung, "/admin/users/999/impersonate")
    assert antwort.status_code == 404


def test_sich_selbst_geht_nicht(umgebung):
    umgebung["ziel"]["row"] = _user(id=1, username="chef")
    antwort = _post(umgebung, "/admin/users/1/impersonate")
    assert antwort.status_code == 403


def test_admin_konto_bleibt_zu(umgebung):
    umgebung["ziel"]["row"] = _user(role="admin")
    antwort = _post(umgebung, "/admin/users/7/impersonate")
    assert antwort.status_code == 403


def test_konto_mit_nutzerverwaltung_bleibt_zu(umgebung, monkeypatch):
    from src import database
    monkeypatch.setattr(
        database, "get_custom_role",
        lambda rid: {"id": rid, "name": "Nutzerverwaltung", "permissions": [PERM_SET_USERS_ALL]},
    )
    umgebung["ziel"]["row"] = _user(role="custom", custom_role_id=5)
    antwort = _post(umgebung, "/admin/users/7/impersonate")
    assert antwort.status_code == 403


def test_lehrende_sind_erreichbar(umgebung):
    """Staff carries a settings key but may not hand out rights, so it stays open."""
    umgebung["ziel"]["row"] = _user(role="staff")
    antwort = _post(umgebung, "/admin/users/7/impersonate")
    assert antwort.status_code == 200


def test_eigene_rolle_ohne_nutzerverwaltung_ist_erreichbar(umgebung, monkeypatch):
    from src import database
    monkeypatch.setattr(
        database, "get_custom_role",
        lambda rid: {"id": rid, "name": "Zahlen", "permissions": [PERM_SET_STATS_USERS]},
    )
    umgebung["ziel"]["row"] = _user(role="custom", custom_role_id=6)
    assert _post(umgebung, "/admin/users/7/impersonate").status_code == 200


def test_gesperrtes_konto_bleibt_zu(umgebung):
    umgebung["ziel"]["row"] = _user(active=0)
    assert _post(umgebung, "/admin/users/7/impersonate").status_code == 403


def test_abgelaufenes_testkonto_bleibt_zu(umgebung):
    umgebung["ziel"]["row"] = _user(access_expires_at=datetime.now() - timedelta(days=1))
    assert _post(umgebung, "/admin/users/7/impersonate").status_code == 403


def test_keine_kette_von_uebernahmen(umgebung):
    _als(umgebung, {**ADMIN, "impersonator": {"user_id": 1, "log_id": 3}})
    assert _post(umgebung, "/admin/users/7/impersonate").status_code == 403


# ─── Der Erfolgsfall ─────────────────────────────────────────────────────────

def test_uebernahme_setzt_neue_sitzung_und_schreibt_protokoll(umgebung):
    antwort = _post(umgebung, "/admin/users/7/impersonate")
    assert antwort.status_code == 200
    assert antwort.json()["display_name"] == "Anna Beispiel"

    neu = antwort.cookies["session"]
    assert neu != "eigene"
    sitzung = umgebung["store"].get_data(neu)
    assert sitzung["user_id"] == 7
    assert sitzung["username"] == "anna"
    assert sitzung["impersonator"]["user_id"] == 1
    assert sitzung["impersonator_token"] == "eigene"
    assert umgebung["log"][0]["target_username"] == "anna"


def test_eigene_sitzung_bleibt_bestehen(umgebung):
    _post(umgebung, "/admin/users/7/impersonate")
    assert umgebung["store"].validate("eigene")


# ─── Der Rueckweg ────────────────────────────────────────────────────────────

def test_stop_ohne_uebernahme_ist_409(umgebung):
    assert _post(umgebung, "/admin/impersonation/stop", "geliehen").status_code == 409


def test_stop_gibt_die_eigene_sitzung_zurueck(umgebung):
    umgebung["store"].data["geliehen"] = dict(GELIEHEN)
    _als(umgebung, GELIEHEN)
    antwort = _post(umgebung, "/admin/impersonation/stop", "geliehen")
    assert antwort.status_code == 200
    assert antwort.cookies["session"] == "eigene"
    assert {"ended": 42, "reason": "manual"} in umgebung["log"]


def test_stop_raeumt_die_geliehene_sitzung_weg(umgebung):
    umgebung["store"].data["geliehen"] = dict(GELIEHEN)
    _als(umgebung, GELIEHEN)
    _post(umgebung, "/admin/impersonation/stop", "geliehen")
    assert not umgebung["store"].validate("geliehen")


def test_stop_ohne_lebende_eigene_sitzung_meldet_sich_ab(umgebung):
    umgebung["store"].destroy("eigene")
    umgebung["store"].data["geliehen"] = dict(GELIEHEN)
    _als(umgebung, GELIEHEN)
    antwort = _post(umgebung, "/admin/impersonation/stop", "geliehen")
    assert antwort.status_code == 409
    assert antwort.cookies.get("session") in (None, "")


def test_stop_braucht_kein_recht(umgebung):
    """The borrowed session may hold nothing at all, the way back still works."""
    umgebung["store"].data["geliehen"] = dict(GELIEHEN)
    _als(umgebung, GELIEHEN)
    assert _post(umgebung, "/admin/impersonation/stop", "geliehen").status_code == 200


# ─── Das Protokoll ───────────────────────────────────────────────────────────

def test_protokoll_braucht_das_recht(umgebung):
    _als(umgebung, {"user_id": 2, "username": "lisa", "role": "user",
                    "email": "lisa@example.org", "custom_role_id": None})
    assert umgebung["client"].get("/admin/impersonation/log", cookies={"session": "eigene"}).status_code == 403


def test_protokoll_liefert_die_liste(umgebung, monkeypatch):
    from src.features.impersonation import repository as repo
    monkeypatch.setattr(repo, "list_entries", lambda limit, offset: [{"id": 1}])
    monkeypatch.setattr(repo, "count_entries", lambda: 1)
    antwort = umgebung["client"].get("/admin/impersonation/log", cookies={"session": "eigene"})
    assert antwort.status_code == 200
    assert antwort.json() == {"entries": [{"id": 1}], "total": 1}


def test_recht_gehoert_zum_admin_vorrat():
    from src.permissions_registry import SYSTEM_ROLE_PERMISSIONS
    assert PERM_SET_USERS_IMPERSONATE in SYSTEM_ROLE_PERMISSIONS["admin"]
    assert PERM_SET_USERS_IMPERSONATE not in SYSTEM_ROLE_PERMISSIONS["staff"]
    assert PERM_SET_USERS_IMPERSONATE not in SYSTEM_ROLE_PERMISSIONS["user"]
