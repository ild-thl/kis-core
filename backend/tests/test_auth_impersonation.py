"""The two places in auth.py that the borrowed session touches."""

import pytest
from fastapi.testclient import TestClient

GELIEHEN = {
    "user_id": 7, "username": "anna", "display_name": "Anna Beispiel",
    "email": "anna@example.org", "role": "user", "custom_role_id": None,
    "access_expires_at": None,
    "impersonator": {"user_id": 1, "username": "chef", "display_name": "Chefin", "log_id": 42},
    "impersonator_token": "eigene",
}


class FakeStore:
    def __init__(self, vorhanden):
        self.data = dict(vorhanden)

    def get_data(self, token):
        return self.data.get(token)

    def validate(self, token) -> bool:
        return token in self.data

    def destroy(self, token) -> None:
        self.data.pop(token, None)


@pytest.fixture
def umgebung(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "chef@example.org")

    from src import database
    from src.app import app
    from src.dependencies import get_settings
    from src.features.impersonation import repository as repo
    from src.routes import auth as route
    from src.security.auth import verify_auth

    get_settings.cache_clear()
    store = FakeStore({"eigene": {"user_id": 1}, "geliehen": dict(GELIEHEN)})
    geschlossen: list[tuple[int, str]] = []

    monkeypatch.setattr(route, "get_session_store", lambda: store)
    monkeypatch.setattr(database, "get_user_by_id", lambda uid: None)
    monkeypatch.setattr(database, "get_custom_role", lambda rid: None)
    monkeypatch.setattr(repo, "end_entry", lambda eid, reason: geschlossen.append((eid, reason)))
    app.dependency_overrides[verify_auth] = lambda: None

    client = TestClient(app)
    client.cookies.set("session", "geliehen", domain="testserver.local")
    yield {"client": client, "store": store, "geschlossen": geschlossen}
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_status_zeigt_wer_dahinter_steckt(umgebung):
    antwort = umgebung["client"].get("/auth/status")
    assert antwort.status_code == 200
    assert antwort.json()["impersonator"]["display_name"] == "Chefin"


def test_status_gibt_den_fremden_schluessel_nicht_heraus(umgebung):
    daten = umgebung["client"].get("/auth/status").json()
    assert "impersonator_token" not in daten
    assert "eigene" not in umgebung["client"].get("/auth/status").text


def test_abmelden_schliesst_den_eintrag_und_beide_sitzungen(umgebung):
    assert umgebung["client"].post("/auth/logout").status_code == 200
    assert umgebung["geschlossen"] == [(42, "logout")]
    assert not umgebung["store"].validate("geliehen")
    assert not umgebung["store"].validate("eigene")
