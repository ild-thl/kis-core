"""One account, created the same way for both ways in, now without a directory."""

from unittest.mock import patch

from src.features.accounts.passwords import verify_password
from src.features.accounts.provisioning import provision_account


def _anlegen(**abweichungen):
    argumente = dict(
        uid="max.mustermann",
        given_name="Max",
        surname="Mustermann",
        email=None,
        role="staff",
        custom_role_id=None,
        password="geheim123",
    )
    argumente.update(abweichungen)
    return provision_account(**argumente)


def test_the_row_carries_a_hash_of_the_password():
    with patch("src.features.accounts.provisioning.database.create_user", return_value=42) as anlegen:
        daten = _anlegen()

    hash_wert = anlegen.call_args.kwargs["password_hash"]
    assert verify_password("geheim123", hash_wert) is True
    assert hash_wert.startswith("$2")
    assert daten["user_id"] == 42
    assert daten["username"] == "max.mustermann"
    assert daten["display_name"] == "Max Mustermann"


def test_without_a_mail_address_nothing_lands_on_the_list():
    with patch("src.features.accounts.provisioning.database.create_user", return_value=42), \
         patch("src.features.accounts.provisioning.database.add_to_whitelist") as liste:
        daten = _anlegen(email=None)

    liste.assert_not_called()
    assert daten["email"] is None


def test_a_given_mail_address_lands_on_the_list():
    with patch("src.features.accounts.provisioning.database.create_user", return_value=42), \
         patch("src.features.accounts.provisioning.database.add_to_whitelist") as liste:
        _anlegen(email="max@example.org")

    liste.assert_called_once_with("max@example.org")


def test_it_falls_back_to_the_user_name_when_no_name_was_given():
    with patch("src.features.accounts.provisioning.database.create_user", return_value=42):
        daten = _anlegen(given_name="", surname="")
    assert daten["display_name"] == "max.mustermann"


def test_a_custom_role_is_set_afterwards():
    with patch("src.features.accounts.provisioning.database.create_user", return_value=42), \
         patch("src.features.accounts.provisioning.database.set_user_role") as rolle:
        daten = _anlegen(role="custom", custom_role_id=3)

    rolle.assert_called_once_with(42, "custom", 3)
    assert daten["custom_role_id"] == 3


def test_the_account_starts_active():
    with patch("src.features.accounts.provisioning.database.create_user", return_value=42) as anlegen:
        _anlegen()
    assert anlegen.call_args.kwargs["active"] == 1
