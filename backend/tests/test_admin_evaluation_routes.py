"""Admin side: create, edit and switch the one evaluation on or off."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.features.evaluation.service import default_config


@pytest.fixture
def client():
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
def client_ohne_recht():
    """A logged-in user without the evaluation right, to prove the gate holds."""
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


def test_get_returns_the_default_seed_on_a_fresh_install(client):
    with patch("src.features.evaluation.repository.get_setting", return_value=""):
        r = client.get("/admin/evaluation")
    assert r.status_code == 200
    assert r.json()["title"] == default_config()["title"]


def test_saving_rejects_an_empty_question_list(client):
    r = client.put("/admin/evaluation", json={"title": "Test", "questions": []})
    assert r.status_code == 400


def test_saving_writes_every_field(client):
    with patch("src.features.evaluation.repository.save_config") as speichern, \
         patch("src.features.evaluation.repository.get_config",
               return_value={"active": False, "for_all": False}):
        r = client.put("/admin/evaluation", json={
            "title": "Kurze Evaluation",
            "intro_text": "Willkommen",
            "outro_text": "Danke",
            "questions": [{"type": "choice", "text": "Wie war's?", "options": ["Gut", "Schlecht"]}],
        })
    assert r.status_code == 200
    gespeichert = speichern.call_args[0][0]
    assert gespeichert["title"] == "Kurze Evaluation"
    assert gespeichert["questions"][0]["text"] == "Wie war's?"


def test_toggling_active_calls_the_repository(client):
    with patch("src.features.evaluation.repository.set_active") as schalten:
        r = client.patch("/admin/evaluation/active", json={"active": True})
    assert r.status_code == 200
    schalten.assert_called_once_with(True)


def test_a_user_without_the_right_is_blocked(client_ohne_recht):
    r = client_ohne_recht.get("/admin/evaluation")
    assert r.status_code == 403


def test_toggling_the_switch_for_everyone_calls_the_repository(client):
    with patch("src.features.evaluation.repository.set_for_all") as schalten:
        r = client.patch("/admin/evaluation/for-all", json={"for_all": True})
    assert r.status_code == 200
    schalten.assert_called_once_with(True)


def test_a_user_without_the_right_cannot_open_it_for_everyone(client_ohne_recht):
    with patch("src.features.evaluation.repository.set_for_all") as schalten:
        r = client_ohne_recht.patch("/admin/evaluation/for-all", json={"for_all": True})
    assert r.status_code == 403
    schalten.assert_not_called()


def test_saving_the_questions_answers_with_both_switches(client):
    """The tab rebuilds its state from this answer, a missing switch would flip in the UI."""
    with patch("src.features.evaluation.repository.save_config"), \
         patch("src.features.evaluation.repository.get_config",
               return_value={"active": True, "for_all": True, "reveal_round": 3}):
        r = client.put("/admin/evaluation", json={
            "title": "Kurze Evaluation",
            "questions": [{"type": "choice", "text": "Wie war's?", "options": ["Gut", "Schlecht"]}],
        })
    assert r.status_code == 200
    assert r.json()["active"] is True
    assert r.json()["for_all"] is True
