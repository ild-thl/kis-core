"""A person can set the level by hand, the profile then shows where it came from."""

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


def _level(level=None, source=None, set_at=None):
    return {"language_level": level, "language_level_set_at": set_at, "language_level_source": source}


def test_put_stores_a_self_chosen_level(client):
    set_at = datetime(2026, 9, 4, tzinfo=timezone.utc)
    with patch(f"{ROUTE}.db.is_language_training_offered", return_value=True), \
         patch(f"{ROUTE}.db.set_user_language_level") as write, \
         patch(f"{ROUTE}.db.get_user_language_level", return_value=_level("B1", "self", set_at)):
        response = client.put("/me/language-level", json={"level": "B1"})

    assert response.status_code == 200
    write.assert_called_once_with(1, "B1", "self")
    body = response.json()
    assert body["language_level"] == "B1"
    assert body["language_level_source"] == "self"
    assert body["language_level_set_at"] == set_at.isoformat()


def test_put_rejects_an_unknown_level(client):
    with patch(f"{ROUTE}.db.is_language_training_offered", return_value=True), \
         patch(f"{ROUTE}.db.set_user_language_level") as write:
        response = client.put("/me/language-level", json={"level": "B3"})

    assert response.status_code == 422
    write.assert_not_called()


def test_put_is_refused_while_the_trainer_is_not_offered(client):
    with patch(f"{ROUTE}.db.is_language_training_offered", return_value=False), \
         patch(f"{ROUTE}.db.set_user_language_level") as write:
        response = client.put("/me/language-level", json={"level": "B1"})

    assert response.status_code == 403
    write.assert_not_called()


def test_get_me_carries_the_level_source(client):
    row = {"id": 1, "username": "a", "display_name": "A", "email": None,
           "role": "user", "locale": "de", "tour_seen_at": None}
    state = {"language_training_active": True, "language_training_asked_at": None}
    with patch(f"{ROUTE}.db.get_user_by_id", return_value=row), \
         patch(f"{ROUTE}.db.get_user_language_level", return_value=_level("A2", "test")), \
         patch(f"{ROUTE}.db.get_user_language_training", return_value=state), \
         patch(f"{ROUTE}.db.is_language_training_offered", return_value=True):
        response = client.get("/me")

    assert response.status_code == 200
    assert response.json()["language_level_source"] == "test"
