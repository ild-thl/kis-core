"""The start question lives at /me, admin switch and permission gate the write."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

ROUTE = "src.routes.me"


@pytest.fixture
def client(monkeypatch):
    # The variable keeps the request out of the database.

    from src.app import app
    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1}
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _state(active=False, asked=None):
    return {"language_training_active": active, "language_training_asked_at": asked}


def test_get_me_carries_the_trainer_fields(client):
    row = {"id": 1, "username": "a", "display_name": "A", "email": None,
           "role": "user", "locale": "de", "tour_seen_at": None}
    with patch(f"{ROUTE}.db.get_user_by_id", return_value=row), \
         patch(f"{ROUTE}.db.get_user_language_level",
               return_value={"language_level": None, "language_level_set_at": None}), \
         patch(f"{ROUTE}.db.get_user_language_training", return_value=_state()), \
         patch(f"{ROUTE}.db.is_language_training_offered", return_value=True):
        response = client.get("/me")

    assert response.status_code == 200
    body = response.json()
    assert body["language_training_enabled"] is True
    assert body["language_training_active"] is False
    assert body["language_training_asked_at"] is None


def test_patch_sets_the_switch_and_answers_the_question(client):
    asked = datetime(2026, 9, 3, tzinfo=timezone.utc)
    with patch(f"{ROUTE}.db.is_language_training_offered", return_value=True), \
         patch(f"{ROUTE}.db.set_user_language_training") as write, \
         patch(f"{ROUTE}.db.get_user_language_training", return_value=_state(True, asked)):
        response = client.patch("/me/language-training", json={"active": True})

    assert response.status_code == 200
    write.assert_called_once_with(1, True)
    assert response.json()["language_training_active"] is True
    assert response.json()["language_training_asked_at"] == asked.isoformat()


def test_no_and_later_only_answer_the_question(client):
    """Both buttons write false, the SQL keeps the first asked_at."""
    with patch(f"{ROUTE}.db.is_language_training_offered", return_value=True), \
         patch(f"{ROUTE}.db.set_user_language_training") as write, \
         patch(f"{ROUTE}.db.get_user_language_training", return_value=_state(False, None)):
        response = client.patch("/me/language-training", json={"active": False})

    assert response.status_code == 200
    write.assert_called_once_with(1, False)


def test_patch_is_refused_while_the_trainer_is_not_offered(client):
    with patch(f"{ROUTE}.db.is_language_training_offered", return_value=False), \
         patch(f"{ROUTE}.db.set_user_language_training") as write:
        response = client.patch("/me/language-training", json={"active": True})

    assert response.status_code == 403
    write.assert_not_called()
