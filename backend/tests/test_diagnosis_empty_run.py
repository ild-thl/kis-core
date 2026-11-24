"""Everything skipped yields a fixed A1, without a model call."""

import pytest

from src.services.aia_diagnosis_chat import is_empty_run


def _run(*answers) -> list[dict]:
    """Builds a history from question and answer pairs."""
    history: list[dict] = []
    for i, item in enumerate(answers, 1):
        text, selected = item if isinstance(item, tuple) else (item, None)
        history.append({"role": "assistant", "content": f"Frage {i}"})
        turn: dict = {"role": "user", "content": text}
        if selected is not None:
            turn["selected"] = selected
        history.append(turn)
    return history


def test_empty_run_when_nothing_was_given():
    assert is_empty_run(_run("", "", "")) is True


def test_empty_run_tolerates_whitespace_answers():
    """A learner who hits space before skipping still gave nothing."""
    assert is_empty_run(_run("", "   ", "\n")) is True


def test_empty_run_ignores_an_empty_selection_list():
    assert is_empty_run(_run(("", []), ("", []))) is True


def test_not_empty_when_any_text_was_typed():
    assert is_empty_run(_run("", "Ich gehe ins Kino.", "")) is False


def test_not_empty_when_an_option_was_clicked():
    """A tick without text is still an answer, so the model grades it."""
    assert is_empty_run(_run("", ("", ["gehe"]), "")) is False


def test_empty_history_is_not_an_empty_run():
    """No answer at all is not an empty run but no run."""
    assert is_empty_run([]) is False


# ─── The endpoint ──────────────────────────────────────────────────────────

from unittest.mock import AsyncMock, patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from src.services.aia_diagnosis_chat import parse_question_plan  # noqa: E402

ROUTE = "src.features.ai_assistant.routes.language_training.diagnosis"


@pytest.fixture
def client(monkeypatch):
    # The variable keeps the request out of the database.

    from src.app import app
    from src.dependencies import get_current_user, get_llm_client, get_settings
    from src.dependencies_rbac import require_aia_access
    from src.security.auth import verify_auth

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[require_aia_access] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1}
    # If the empty branch did reach for a provider, it would show up here.
    app.dependency_overrides[get_llm_client] = lambda: object()
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _full_skip_history() -> list[dict]:
    """A finished German run in which every single question was skipped."""
    total = len(parse_question_plan(""))
    return _run(*[""] * total)


def test_all_skipped_gives_a_fixed_a1_without_asking_the_model(client):
    with patch(f"{ROUTE}.db.is_language_training_offered", return_value=True), \
         patch(f"{ROUTE}.db.get_setting", side_effect=lambda key, default="": default), \
         patch(f"{ROUTE}.db.set_user_language_level") as save, \
         patch(f"{ROUTE}._ask") as call_llm:
        response = client.post(
            "/ai-assistant/language-diagnosis/turn",
            json={"history": _full_skip_history()},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["done"] is True
    assert body["level"] == "A1"
    assert body["message"].strip()
    call_llm.assert_not_called()
    save.assert_called_once_with(1, "A1")


def test_a_single_answer_still_goes_to_the_model(client):
    """One typed sentence is enough, then the normal grading runs."""
    history = _full_skip_history()
    history[1]["content"] = "Ich gehe ins Kino."

    with patch(f"{ROUTE}.db.is_language_training_offered", return_value=True), \
         patch(f"{ROUTE}.db.get_setting", side_effect=lambda key, default="": default), \
         patch(f"{ROUTE}.db.set_user_language_level"), \
         patch(f"{ROUTE}.enforce_aia_burst"), \
         patch(f"{ROUTE}._ask", new=AsyncMock(
             return_value='{"done": true, "message": "Weiter so.", "level": "A2"}',
         )) as call_llm:
        response = client.post(
            "/ai-assistant/language-diagnosis/turn",
            json={"history": history},
        )

    assert response.status_code == 200
    assert response.json()["level"] == "A2"
    assert call_llm.await_count == 1


def test_a_person_without_the_trainer_gets_no_question(client):
    """Offered decides, not a module, so the body carries no workspace any more."""
    with patch(f"{ROUTE}.db.is_language_training_offered", return_value=False), \
         patch(f"{ROUTE}._ask") as call_llm:
        response = client.post(
            "/ai-assistant/language-diagnosis/turn",
            json={"history": []},
        )

    assert response.status_code == 403
    call_llm.assert_not_called()
