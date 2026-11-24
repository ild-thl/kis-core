"""Contact address, imprint and privacy policy as system settings: saved, checked, logged and read openly."""

import logging

import pytest
from fastapi import HTTPException

from src.permissions_registry import PERM_SET_SYSTEM, SETTING_FIELD_PERMISSIONS
from src.routes import health
from src.routes.admin import settings as admin_settings

_ADMIN = {"role": "admin", "username": "chefin"}
KEYS = health.LEGAL_KEYS


class _Body:
    """Minimal stand-in for UpdateSettingsRequest: everything None except the given fields."""

    def __init__(self, **kwargs):
        object.__setattr__(self, "_set", kwargs)

    def __getattr__(self, name):
        return object.__getattribute__(self, "_set").get(name)

    def model_dump(self):
        return dict(object.__getattribute__(self, "_set"))


@pytest.fixture
def store(monkeypatch):
    data = {"secret_api_key": "geheim"}
    get = lambda key, default="": data.get(key, default)  # noqa: E731
    monkeypatch.setattr(admin_settings.db, "get_setting", get)
    monkeypatch.setattr(admin_settings.db, "set_setting", lambda key, value: data.__setitem__(key, value))
    monkeypatch.setattr(health.db, "get_setting", get)
    return data


def test_only_the_system_permission_may_write_them():
    assert all(SETTING_FIELD_PERMISSIONS[key] == PERM_SET_SYSTEM for key in KEYS)


def test_a_fresh_installation_has_empty_texts(store):
    labels = health.ui_labels()
    assert all(labels[key] == "" for key in KEYS)


def test_saved_texts_are_open_to_everyone_and_nothing_else_leaks(store):
    admin_settings.update_settings(_Body(legal_imprint_de="### Angaben\n\nName", legal_contact_email="a@example.org"), _ADMIN, "de")

    labels = health.ui_labels()
    assert labels["legal_imprint_de"] == "### Angaben\n\nName"
    assert labels["legal_contact_email"] == "a@example.org"
    assert "geheim" not in str(labels)


def test_the_admin_page_reads_them_back(store):
    admin_settings.update_settings(_Body(legal_privacy_en="## 1. Controller"), _ADMIN, "de")
    assert admin_settings.get_settings(_ADMIN)["legal_privacy_en"] == "## 1. Controller"


@pytest.mark.parametrize("email", ["keine-adresse", "a@b", "a b@c.de"])
def test_a_wrong_contact_address_is_refused(store, email):
    with pytest.raises(HTTPException) as e:
        admin_settings.update_settings(_Body(legal_contact_email=email), _ADMIN, "en")
    assert e.value.status_code == 400
    assert e.value.detail == "The email address is not valid."


def test_an_empty_contact_address_is_allowed(store):
    store["legal_contact_email"] = "a@example.org"
    admin_settings.update_settings(_Body(legal_contact_email="  "), _ADMIN, "de")
    assert store["legal_contact_email"] == ""


def test_a_text_over_the_limit_is_refused(store):
    with pytest.raises(HTTPException) as e:
        admin_settings.update_settings(_Body(legal_imprint_de="x" * (admin_settings.MAX_LEGAL_CHARS + 1)), _ADMIN, "de")
    assert e.value.status_code == 400


def test_a_change_leaves_a_log_line(store, caplog):
    with caplog.at_level(logging.INFO, logger="src.routes.admin.settings"):
        admin_settings.update_settings(_Body(legal_imprint_en="Imprint"), _ADMIN, "de")
    assert any("chefin" in m and "legal_imprint_en" in m for m in caplog.messages)
