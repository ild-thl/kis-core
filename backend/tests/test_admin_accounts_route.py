"""Creating an account by hand, the third way in next to invitation and code."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

ADMIN = {"user_id": 1, "username": "chefin", "display_name": "Chefin",
         "email": "admin@th-luebeck.de", "role": "admin", "custom_role_id": None}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "admin@th-luebeck.de")
    from src.app import app
    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: dict(ADMIN)
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _payload(**abweichungen):
    daten = {"uid": "max.mustermann", "given_name": "Max", "surname": "Mustermann",
             "kis_role": "staff"}
    daten.update(abweichungen)
    return daten


def test_an_account_is_created_and_the_password_comes_back(client):
    with patch("src.routes.admin.accounts.database.get_user_by_username", return_value=None), \
         patch("src.routes.admin.accounts.provision_account") as anlegen:
        r = client.post("/admin/accounts", json=_payload())

    assert r.status_code == 200
    body = r.json()
    assert body["uid"] == "max.mustermann"
    assert len(body["generated_password"]) >= 12
    assert anlegen.call_args.kwargs["password"] == body["generated_password"]
    assert anlegen.call_args.kwargs["email"] is None


def test_a_given_mail_address_is_passed_on(client):
    with patch("src.routes.admin.accounts.database.get_user_by_username", return_value=None), \
         patch("src.routes.admin.accounts.database.get_user_by_email", return_value=None), \
         patch("src.routes.admin.accounts.provision_account") as anlegen:
        r = client.post("/admin/accounts", json=_payload(email="max@th-luebeck.de"))

    assert r.status_code == 200
    assert anlegen.call_args.kwargs["email"] == "max@th-luebeck.de"


def test_an_at_sign_in_the_user_name_is_refused(client):
    # The login field tells a mail from a name by the @, such a name would break it.
    with patch("src.routes.admin.accounts.provision_account") as anlegen:
        r = client.post("/admin/accounts", json=_payload(uid="max@th-luebeck.de"))

    assert r.status_code == 400
    anlegen.assert_not_called()


def test_a_mail_address_without_an_at_sign_is_refused(client):
    with patch("src.routes.admin.accounts.provision_account") as anlegen:
        r = client.post("/admin/accounts", json=_payload(email="kein-mail"))

    assert r.status_code == 400
    anlegen.assert_not_called()


def test_a_user_name_that_is_taken_reports_a_conflict(client):
    with patch("src.routes.admin.accounts.database.get_user_by_username", return_value={"id": 4}), \
         patch("src.routes.admin.accounts.provision_account") as anlegen:
        r = client.post("/admin/accounts", json=_payload())

    assert r.status_code == 409
    anlegen.assert_not_called()


def test_a_mail_address_that_is_taken_reports_a_conflict(client):
    with patch("src.routes.admin.accounts.database.get_user_by_username", return_value=None), \
         patch("src.routes.admin.accounts.database.get_user_by_email", return_value={"id": 4}), \
         patch("src.routes.admin.accounts.provision_account") as anlegen:
        r = client.post("/admin/accounts", json=_payload(email="max@th-luebeck.de"))

    assert r.status_code == 409
    anlegen.assert_not_called()


def test_a_custom_role_without_an_id_is_refused_by_the_model(client):
    r = client.post("/admin/accounts", json=_payload(kis_role="custom"))
    assert r.status_code == 422


def test_an_unknown_custom_role_is_refused(client):
    with patch("src.routes.admin.accounts.database.get_custom_role", return_value=None), \
         patch("src.routes.admin.accounts.provision_account") as anlegen:
        r = client.post("/admin/accounts", json=_payload(kis_role="custom", custom_role_id=9))

    assert r.status_code == 400
    anlegen.assert_not_called()


def test_a_failing_creation_reports_a_server_error(client):
    with patch("src.routes.admin.accounts.database.get_user_by_username", return_value=None), \
         patch("src.routes.admin.accounts.provision_account", side_effect=RuntimeError("weg")):
        r = client.post("/admin/accounts", json=_payload())

    assert r.status_code == 500


