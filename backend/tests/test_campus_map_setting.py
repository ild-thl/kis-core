"""The campus map address is a system setting: only the system right writes it, only web addresses pass."""

import pytest
from fastapi import HTTPException

from src.permissions_registry import PERM_SET_SYSTEM, SETTING_FIELD_PERMISSIONS
from src.routes.admin import settings as admin_settings
from src.routes.admin._models import UpdateSettingsRequest


@pytest.fixture
def written(monkeypatch):
    out = {}
    monkeypatch.setattr(admin_settings.campus_settings, "write", lambda values: out.update(values))
    return out


def test_only_the_system_right_writes_the_map():
    assert SETTING_FIELD_PERMISSIONS["campus_map_url"] == PERM_SET_SYSTEM
    assert SETTING_FIELD_PERMISSIONS["campus_map_enabled"] == PERM_SET_SYSTEM


def test_address_and_switch_are_saved(written):
    body = UpdateSettingsRequest(campus_map_url="  https://map.test/campus-map/index.html ", campus_map_enabled=False)
    admin_settings._save_campus_map(body, "de")
    assert written == {"map_url": "https://map.test/campus-map/index.html", "map_enabled": False}


def test_empty_address_switches_the_map_off(written):
    admin_settings._save_campus_map(UpdateSettingsRequest(campus_map_url=""), "de")
    assert written == {"map_url": ""}


def test_no_script_address(written):
    with pytest.raises(HTTPException) as info:
        admin_settings._save_campus_map(UpdateSettingsRequest(campus_map_url="javascript:alert(1)"), "de")
    assert info.value.status_code == 400 and written == {}


def test_nothing_sent_nothing_written(written):
    admin_settings._save_campus_map(UpdateSettingsRequest(), "de")
    assert written == {}
