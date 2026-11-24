"""The interpreter translates single sentences straight away and never creates a job."""

import pytest
from fastapi.testclient import TestClient

from src.permissions import Permissions
from src.services.glossary import GlossaryService


class _FakeClient:
    def translate_text(self, text, source_lang, target_lang):
        return f"[{target_lang}] {text}"


def _out_of_local_mode(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")


def _client(monkeypatch, tools):
    _out_of_local_mode(monkeypatch)
    from src.dependencies import get_current_user, get_settings
    from src.dependencies_rbac import get_user_permissions
    from src.security.auth import verify_auth
    from src.app import app
    import src.routes.interpreter as route

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "email": "a@th-luebeck.de", "role": "staff"}
    app.dependency_overrides[get_user_permissions] = lambda: Permissions(keys=frozenset(tools))
    monkeypatch.setattr("src.dependencies_rbac.is_released_now", lambda key: True)
    monkeypatch.setattr(route, "enforce_tool_burst", lambda *a, **k: None)
    monkeypatch.setattr(route, "get_translate_client_for_provider",
                        lambda pid, glossary_entries=None: (_FakeClient(), GlossaryService()))
    return TestClient(app)


@pytest.fixture
def client(monkeypatch):
    yield _client(monkeypatch, {"tools.interpreter"})
    from src.app import app
    app.dependency_overrides.clear()


@pytest.fixture
def client_ohne_werkzeug(monkeypatch):
    yield _client(monkeypatch, set())
    from src.app import app
    app.dependency_overrides.clear()


def test_uebersetzt_einen_satz_ohne_auftrag(client, monkeypatch):
    def kein_auftrag(*a, **k):
        raise AssertionError("a job was created")
    monkeypatch.setattr("src.database.create_job", kein_auftrag)

    r = client.post("/interpreter/translate", json={"text": "Wo ist die Mensa?", "target_lang": "EN-US"})

    assert r.status_code == 200, r.text
    assert r.json()["text"] == "[EN-US] Wo ist die Mensa?"


def test_unbekannte_sprache_wird_abgelehnt(client):
    r = client.post("/interpreter/translate", json={"text": "Hallo", "target_lang": "FR"})
    assert r.status_code == 400


def test_leerer_text_wird_abgelehnt(client):
    r = client.post("/interpreter/translate", json={"text": "   ", "target_lang": "DE"})
    assert r.status_code == 400


def test_ohne_anbieter_kommt_503(client, monkeypatch):
    import src.routes.interpreter as route
    monkeypatch.setattr(route, "get_translate_client_for_provider",
                        lambda pid, glossary_entries=None: (None, GlossaryService()))
    r = client.post("/interpreter/translate", json={"text": "Hallo", "target_lang": "EN-US"})
    assert r.status_code == 503


def test_ohne_werkzeugrecht_kommt_403(client_ohne_werkzeug):
    r = client_ohne_werkzeug.post("/interpreter/translate", json={"text": "Hallo", "target_lang": "EN-US"})
    assert r.status_code == 403
