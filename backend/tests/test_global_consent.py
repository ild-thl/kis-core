"""The one notice every account confirms once, before any service is reachable - same for all."""
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.dependencies_rbac import get_current_user, get_user_permissions, require_tool_access
from src.permissions import permissions_for_system_role
from src.services.consent import GLOBAL_CONSENT_VERSION, has_global_consent


# ── The version check itself ────────────────────────────────────────────────

def test_without_a_version_consent_is_missing():
    with patch("src.services.consent.db.get_global_consent", return_value={"global_consent_version": None}):
        assert has_global_consent(7) is False


def test_at_the_current_version_consent_stands():
    with patch("src.services.consent.db.get_global_consent", return_value={"global_consent_version": GLOBAL_CONSENT_VERSION}):
        assert has_global_consent(7) is True


def test_without_a_user_id_nobody_is_asked():
    """No session, no row to check - blocked without a database round trip."""
    with patch("src.services.consent.db.get_global_consent") as get:
        assert has_global_consent(None) is False
        get.assert_not_called()


# ── Every service gate shares it, whatever the role ─────────────────────────

def _build_client(role: str) -> TestClient:
    app = FastAPI()

    @app.get("/translate", dependencies=[Depends(require_tool_access("translation"))])
    def tool_route():
        return {"ok": True}

    app.dependency_overrides[get_current_user] = lambda: {"user_id": 7, "role": role}
    app.dependency_overrides[get_user_permissions] = lambda: permissions_for_system_role(role)
    return TestClient(app)


@pytest.mark.parametrize("role", ["staff", "admin", "user"])
def test_without_consent_every_role_is_blocked(role, monkeypatch):
    """TH account, external access or demo - the role does not matter here, only the checkbox."""
    import src.dependencies_rbac as rbac
    monkeypatch.setattr(rbac, "has_global_consent", lambda user_id: False)
    r = _build_client(role).get("/translate")
    assert r.status_code == 403
    assert r.json()["detail"] == "Bitte bestätige zuerst den Hinweis beim ersten Login."


def test_staff_reaches_the_tool_once_consent_is_given():
    r = _build_client("staff").get("/translate")
    assert r.status_code == 200


# ── The endpoints a browser actually calls ──────────────────────────────────

@pytest.fixture
def client_as():
    from src.app import app
    from src.security.auth import verify_auth

    def make(user_id=7):
        app.dependency_overrides[verify_auth] = lambda: None
        app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id, "role": "user"}
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("get", "/glossaries", {}),
        ("get", "/evaluation/active", {}),
        ("get", "/jobs/my", {}),
        ("post", "/feedback", {"data": {"category": "bug", "message": "test"}}),
    ],
)
def test_routers_without_their_own_permission_still_need_consent(method, path, kwargs, client_as, monkeypatch):
    """glossaries, evaluation, jobs, feedback gate only on login - consent must close that gap too."""
    import src.dependencies_rbac as rbac
    monkeypatch.setattr(rbac, "has_global_consent", lambda user_id: False)
    r = getattr(client_as(), method)(path, **kwargs)
    assert r.status_code == 403
    assert r.json()["detail"] == "Bitte bestätige zuerst den Hinweis beim ersten Login."


def test_accepting_consent_stores_the_current_version(client_as):
    with patch("src.routes.me.db.set_global_consent") as set_consent:
        r = client_as().post("/me/consent")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    set_consent.assert_called_once_with(7, GLOBAL_CONSENT_VERSION)


def test_me_reports_whether_consent_was_given():
    from datetime import datetime

    from src.app import app
    from src.security.auth import verify_auth

    row = {
        "id": 7, "username": "pat", "display_name": "Pat", "email": "", "role": "user",
        "locale": "de", "tour_seen_at": None, "global_consent_at": datetime(2026, 10, 9),
    }
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 7, "role": "user"}
    try:
        with patch("src.routes.me.db.get_user_by_id", return_value=row), \
             patch("src.routes.me.has_global_consent", return_value=True), \
             patch("src.routes.me.db.get_user_language_training",
                   return_value={"language_training_active": False, "language_training_asked_at": None}), \
             patch("src.routes.me.db.is_language_training_offered", return_value=False), \
             patch("src.routes.me.db.get_user_language_level",
                   return_value={"language_level": None, "language_level_set_at": None, "language_level_source": None}):
            r = TestClient(app).get("/me")
        assert r.status_code == 200
        body = r.json()
        assert body["global_consent_accepted"] is True
        assert body["global_consent_at"] == "2026-10-09T00:00:00"
    finally:
        app.dependency_overrides.clear()
