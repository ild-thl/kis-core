"""Adding to the list now activates the account, removing deactivates it."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


ADMIN = {"user_id": 1, "username": "chefin", "display_name": "Chefin",
         "email": "admin@example.org", "role": "admin", "custom_role_id": None}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.org")
    from src.app import app
    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: dict(ADMIN)
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_adding_an_address_activates_the_matching_account(client):
    with patch("src.routes.admin.users.db.add_to_whitelist") as liste, \
         patch("src.routes.admin.users.db.get_user_by_email", return_value={"id": 4}), \
         patch("src.routes.admin.users.db.activate_user") as aktiv:
        antwort = client.post("/admin/whitelist", json={"email": "max@example.org"})

    assert antwort.status_code == 200
    liste.assert_called_once_with("max@example.org")
    aktiv.assert_called_once_with(4)


def test_an_address_without_an_account_only_lands_on_the_list(client):
    with patch("src.routes.admin.users.db.add_to_whitelist") as liste, \
         patch("src.routes.admin.users.db.get_user_by_email", return_value=None), \
         patch("src.routes.admin.users.db.activate_user") as aktiv:
        antwort = client.post("/admin/whitelist", json={"email": "neu@example.org"})

    assert antwort.status_code == 200
    liste.assert_called_once_with("neu@example.org")
    aktiv.assert_not_called()


def test_an_address_without_an_at_sign_is_refused(client):
    antwort = client.post("/admin/whitelist", json={"email": "kein-mail"})
    assert antwort.status_code == 400


def test_removing_an_address_deactivates_the_account(client):
    with patch("src.routes.admin.users.db.remove_from_whitelist") as liste, \
         patch("src.routes.admin.users.db.deactivate_user_by_email") as sperren:
        antwort = client.delete("/admin/whitelist/max@example.org")

    assert antwort.status_code == 200
    liste.assert_called_once()
    sperren.assert_called_once()


def test_the_admin_from_the_env_cannot_be_removed(client):
    antwort = client.delete("/admin/whitelist/admin@example.org")
    assert antwort.status_code == 403
