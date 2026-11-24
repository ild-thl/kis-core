"""Filling out the evaluation as a logged-in tester."""
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
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42, "email": "t@example.org"}
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def client_admin():
    """Whoever may configure the evaluation always reaches it, code or no code."""
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


@pytest.fixture(autouse=True)
def code_zeigt_evaluation():
    """Default for these tests: the account came from a code with the switch on."""
    with patch("src.features.access_codes.repository.shows_evaluation", return_value=True):
        yield


@pytest.fixture(autouse=True)
def hat_aktivitaet():
    """Default for these tests: the account has already done something on the platform."""
    with patch("src.features.evaluation.repository.has_platform_activity", return_value=True):
        yield


def _config(active: bool, **abweichungen):
    config = {**default_config(), "active": active}
    config.update(abweichungen)
    return config


def test_inactive_evaluation_hides_its_content(client):
    with patch("src.features.evaluation.repository.get_config", return_value=_config(False)):
        r = client.get("/evaluation/active")
    assert r.json() == {"active": False}


def test_active_evaluation_reports_whether_this_user_already_answered(client):
    with patch("src.features.evaluation.repository.get_config", return_value=_config(True)), \
         patch("src.features.evaluation.repository.has_responded", return_value=True) as pruefen:
        r = client.get("/evaluation/active")
    assert r.json()["already_responded"] is True
    pruefen.assert_called_once_with(42)


def test_an_account_whose_code_has_no_evaluation_sees_nothing(client):
    with patch("src.features.evaluation.repository.get_config", return_value=_config(True)), \
         patch("src.features.access_codes.repository.shows_evaluation", return_value=False):
        r = client.get("/evaluation/active")
    assert r.json() == {"active": False}


def test_an_account_from_a_code_with_the_switch_sees_the_evaluation(client):
    with patch("src.features.evaluation.repository.get_config", return_value=_config(True)), \
         patch("src.features.evaluation.repository.has_responded", return_value=False), \
         patch("src.features.access_codes.repository.shows_evaluation", return_value=True) as fragen:
        r = client.get("/evaluation/active")
    assert r.json()["active"] is True
    fragen.assert_called_once_with(42)


def test_an_admin_sees_the_evaluation_without_any_code(client_admin):
    with patch("src.features.evaluation.repository.get_config", return_value=_config(True)), \
         patch("src.features.evaluation.repository.has_responded", return_value=False), \
         patch("src.features.access_codes.repository.shows_evaluation", return_value=False) as fragen:
        r = client_admin.get("/evaluation/active")
    assert r.json()["active"] is True
    fragen.assert_not_called()


def test_submitting_without_the_switch_on_the_code_is_rejected(client):
    config = _config(True)
    with patch("src.features.evaluation.repository.get_config", return_value=config), \
         patch("src.features.access_codes.repository.shows_evaluation", return_value=False), \
         patch("src.features.evaluation.repository.create_response") as speichern:
        r = client.post("/evaluation/submit", json={
            "answers": [{"question_id": config["questions"][0]["id"], "value": 2}],
        })
    assert r.status_code == 404
    speichern.assert_not_called()


def test_submitting_to_an_inactive_evaluation_is_rejected(client):
    with patch("src.features.evaluation.repository.get_config", return_value=_config(False)):
        r = client.post("/evaluation/submit", json={"answers": []})
    assert r.status_code == 404


def test_answering_again_is_allowed(client):
    """Redoing it is a deliberate choice, reachable through the settings menu,
    so a prior answer must never block a new submission."""
    config = _config(True)
    frage_id = config["questions"][0]["id"]
    with patch("src.features.evaluation.repository.get_config", return_value=config), \
         patch("src.features.evaluation.repository.has_responded", return_value=True), \
         patch("src.features.evaluation.repository.create_response", return_value=9) as speichern:
        r = client.post("/evaluation/submit", json={
            "answers": [{"question_id": frage_id, "value": 2}],
        })
    assert r.status_code == 200
    speichern.assert_called_once_with(42, [{"question_id": frage_id, "value": 2}])


def test_a_valid_submission_is_stored_for_the_current_user(client):
    config = _config(True)
    frage_id = config["questions"][0]["id"]
    with patch("src.features.evaluation.repository.get_config", return_value=config), \
         patch("src.features.evaluation.repository.has_responded", return_value=False), \
         patch("src.features.evaluation.repository.create_response", return_value=9) as speichern:
        r = client.post("/evaluation/submit", json={
            "answers": [{"question_id": frage_id, "value": 4}],
        })
    assert r.status_code == 200
    speichern.assert_called_once_with(42, [{"question_id": frage_id, "value": 4}])


def test_the_switch_for_everyone_lets_in_an_account_without_a_code(client):
    with patch("src.features.evaluation.repository.get_config", return_value=_config(True, for_all=True)), \
         patch("src.features.evaluation.repository.has_responded", return_value=False), \
         patch("src.features.access_codes.repository.shows_evaluation", return_value=False) as fragen:
        r = client.get("/evaluation/active")
    assert r.json()["active"] is True
    fragen.assert_not_called()


def test_the_response_reports_whether_the_account_has_done_anything(client):
    with patch("src.features.evaluation.repository.get_config", return_value=_config(True)), \
         patch("src.features.evaluation.repository.has_responded", return_value=False), \
         patch("src.features.evaluation.repository.has_platform_activity", return_value=False):
        r = client.get("/evaluation/active")
    assert r.json()["active"] is True
    assert r.json()["has_activity"] is False


def test_an_admin_always_counts_as_having_activity(client_admin):
    """The permission is meant for previewing, an admin's own activity must never gate that."""
    with patch("src.features.evaluation.repository.get_config", return_value=_config(True)), \
         patch("src.features.evaluation.repository.has_responded", return_value=False), \
         patch("src.features.evaluation.repository.has_platform_activity", return_value=False) as pruefen:
        r = client_admin.get("/evaluation/active")
    assert r.json()["has_activity"] is True
    pruefen.assert_not_called()


def test_no_activity_still_allows_the_deliberate_submission(client):
    """Reachable through the settings menu, regardless of what steers the tile's own pop-up."""
    config = _config(True)
    frage_id = config["questions"][0]["id"]
    with patch("src.features.evaluation.repository.get_config", return_value=config), \
         patch("src.features.evaluation.repository.has_responded", return_value=False), \
         patch("src.features.evaluation.repository.has_platform_activity", return_value=False), \
         patch("src.features.evaluation.repository.create_response", return_value=9) as speichern:
        r = client.post("/evaluation/submit", json={
            "answers": [{"question_id": frage_id, "value": 2}],
        })
    assert r.status_code == 200
    speichern.assert_called_once_with(42, [{"question_id": frage_id, "value": 2}])


def test_the_switch_for_everyone_also_accepts_their_submission(client):
    config = _config(True, for_all=True)
    frage_id = config["questions"][0]["id"]
    with patch("src.features.evaluation.repository.get_config", return_value=config), \
         patch("src.features.evaluation.repository.has_responded", return_value=False), \
         patch("src.features.access_codes.repository.shows_evaluation", return_value=False), \
         patch("src.features.evaluation.repository.create_response", return_value=9) as speichern:
        r = client.post("/evaluation/submit", json={
            "answers": [{"question_id": frage_id, "value": 3}],
        })
    assert r.status_code == 200
    speichern.assert_called_once_with(42, [{"question_id": frage_id, "value": 3}])
