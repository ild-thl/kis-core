"""The admin account from the .env, kept in step with it on every start."""

from unittest.mock import patch

import pytest

from src.features.accounts.env_admin import ensure_env_admin


@pytest.fixture
def db(monkeypatch):
    """Every database call the module makes, as one settable double."""
    from src.features.accounts import env_admin

    zustand = {
        "setting": "",
        "by_id": None,
        "by_email": None,
        "by_username": None,
        "aufrufe": {},
    }

    def merken(name):
        def _f(*args, **kwargs):
            zustand["aufrufe"].setdefault(name, []).append((args, kwargs))
            return 99 if name == "create_user" else None
        return _f

    monkeypatch.setattr(env_admin.database, "get_setting", lambda k, d="": zustand["setting"])
    monkeypatch.setattr(env_admin.database, "set_setting", merken("set_setting"))
    monkeypatch.setattr(env_admin.database, "get_user_by_id", lambda i: zustand["by_id"])
    monkeypatch.setattr(env_admin.database, "get_user_by_email", lambda e: zustand["by_email"])
    monkeypatch.setattr(env_admin.database, "get_user_by_username", lambda n: zustand["by_username"])
    monkeypatch.setattr(env_admin.database, "create_user", merken("create_user"))
    monkeypatch.setattr(env_admin.database, "set_user_password", merken("set_user_password"))
    monkeypatch.setattr(env_admin.database, "add_to_whitelist", merken("add_to_whitelist"))
    monkeypatch.setattr(env_admin, "_rename_and_remail", merken("_rename_and_remail"))
    return zustand


def _konto(**felder):
    basis = {"id": 1, "username": "a", "email": "alt@example.org",
             "password_hash": "$2b$12$alterhash", "display_name": "Hans"}
    basis.update(felder)
    return basis


def test_nothing_happens_without_a_mail_address(db):
    assert ensure_env_admin("", "geheim123", "chefin") is None
    assert "create_user" not in db["aufrufe"]


def test_nothing_happens_without_a_password(db):
    assert ensure_env_admin("chefin@example.org", "", "chefin") is None
    assert "create_user" not in db["aufrufe"]


def test_a_missing_account_is_created_with_all_three_values(db):
    assert ensure_env_admin("chefin@example.org", "geheim123", "chefin") == 99

    kwargs = db["aufrufe"]["create_user"][0][1]
    assert kwargs["username"] == "chefin"
    assert kwargs["email"] == "chefin@example.org"
    assert kwargs["role"] == "admin"
    assert kwargs["password_hash"].startswith("$2")


def test_without_a_user_name_the_local_part_is_used(db):
    ensure_env_admin("chefin@example.org", "geheim123", "")
    assert db["aufrufe"]["create_user"][0][1]["username"] == "chefin"


def test_the_new_account_is_remembered_for_the_next_start(db):
    ensure_env_admin("chefin@example.org", "geheim123", "chefin")
    assert db["aufrufe"]["set_setting"][0][0] == ("env_admin_user_id", "99")


def test_a_remembered_account_gets_all_three_values_overwritten(db):
    db["setting"] = "1"
    db["by_id"] = _konto()

    assert ensure_env_admin("chefin@example.org", "geheim123", "chefin") == 1

    assert "create_user" not in db["aufrufe"]
    args = db["aufrufe"]["_rename_and_remail"][0][0]
    assert args == (1, "chefin", "chefin@example.org")
    assert db["aufrufe"]["set_user_password"][0][0][0] == 1
    assert db["aufrufe"]["set_user_password"][0][0][1].startswith("$2")


def test_the_mail_address_lands_on_the_list_as_well(db):
    db["setting"] = "1"
    db["by_id"] = _konto()
    ensure_env_admin("chefin@example.org", "geheim123", "chefin")
    assert db["aufrufe"]["add_to_whitelist"][0][0] == ("chefin@example.org",)


def test_without_a_note_the_mail_address_finds_the_account(db):
    # First start after the change, nothing is noted yet.
    db["by_email"] = _konto(id=5)
    assert ensure_env_admin("alt@example.org", "geheim123", "chefin") == 5
    assert db["aufrufe"]["_rename_and_remail"][0][0] == (5, "chefin", "alt@example.org")


def test_without_a_note_the_user_name_also_finds_the_account(db):
    db["by_username"] = _konto(id=7)
    assert ensure_env_admin("ganz-neu@example.org", "geheim123", "a") == 7


def test_a_noted_account_that_is_gone_falls_back_to_the_mail(db):
    db["setting"] = "42"
    db["by_id"] = None
    db["by_email"] = _konto(id=5)
    assert ensure_env_admin("alt@example.org", "geheim123", "chefin") == 5


def test_a_user_name_with_an_at_sign_is_refused(db):
    # The login field tells a mail from a name by the @, such a name would break it.
    db["setting"] = "1"
    db["by_id"] = _konto()
    ensure_env_admin("chefin@example.org", "geheim123", "chef@example.org")

    # The name stays as it was, the rest still goes through.
    assert db["aufrufe"]["_rename_and_remail"][0][0] == (1, "a", "chefin@example.org")


def test_a_user_name_taken_by_somebody_else_is_refused(db):
    db["setting"] = "1"
    db["by_id"] = _konto()
    db["by_username"] = _konto(id=2, username="chefin")
    ensure_env_admin("chefin@example.org", "geheim123", "chefin")

    assert db["aufrufe"]["_rename_and_remail"][0][0] == (1, "a", "chefin@example.org")


def test_a_password_beyond_the_limit_does_not_stop_the_start(db):
    db["setting"] = "1"
    db["by_id"] = _konto()
    assert ensure_env_admin("chefin@example.org", "x" * 100, "chefin") == 1
    assert "set_user_password" not in db["aufrufe"]


def test_production_refuses_to_start_with_the_example_password(monkeypatch):
    """The value shipped in .env.example is worthless as a real password."""
    monkeypatch.setenv("PRODUCTION", "true")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminpw")
    from fastapi.testclient import TestClient

    from src.app import create_app
    from src.dependencies import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
            with TestClient(create_app()):
                pass
    finally:
        get_settings.cache_clear()


def test_the_guard_matches_the_value_in_env_example():
    """If somebody changes one, the other has to move too."""
    from pathlib import Path

    from src.app import _BEISPIEL_ADMIN_PASSWORT

    beispiel = Path(__file__).resolve().parents[2] / ".env.example"
    if not beispiel.exists():
        # The container only carries backend/, there the file is out of reach.
        pytest.skip(".env.example not reachable from here")
    zeilen = [z for z in beispiel.read_text().splitlines() if z.startswith("ADMIN_PASSWORD=")]
    assert zeilen == [f"ADMIN_PASSWORD={_BEISPIEL_ADMIN_PASSWORT}"]
