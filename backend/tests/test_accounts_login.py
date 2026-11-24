"""One field, two keys: a mail address carries an @, a user name never does."""

import base64
import hashlib
import os
from unittest.mock import patch

from src.features.accounts.login import authenticate, find_user
from src.features.accounts.passwords import hash_password


def _ssha(password: str) -> str:
    salt = os.urandom(4)
    digest = hashlib.sha1(password.encode("utf-8") + salt).digest()
    return "{SSHA}" + base64.b64encode(digest + salt).decode("ascii")


def test_an_input_with_an_at_sign_goes_to_the_mail_lookup():
    with patch("src.features.accounts.login.database.get_user_by_email", return_value={"id": 1}) as mail, \
         patch("src.features.accounts.login.database.get_user_by_username") as name:
        assert find_user("max@example.org")["id"] == 1
    mail.assert_called_once_with("max@example.org")
    name.assert_not_called()


def test_an_input_without_an_at_sign_goes_to_the_name_lookup():
    with patch("src.features.accounts.login.database.get_user_by_email") as mail, \
         patch("src.features.accounts.login.database.get_user_by_username", return_value={"id": 2}) as name:
        assert find_user("max.mustermann")["id"] == 2
    name.assert_called_once_with("max.mustermann")
    mail.assert_not_called()


def test_surrounding_spaces_do_not_matter():
    with patch("src.features.accounts.login.database.get_user_by_username", return_value={"id": 2}) as name:
        find_user("  max.mustermann  ")
    name.assert_called_once_with("max.mustermann")


def test_an_empty_input_finds_nothing():
    assert find_user("") is None
    assert find_user("   ") is None


def test_the_right_password_returns_the_account():
    konto = {"id": 5, "password_hash": hash_password("geheim123")}
    with patch("src.features.accounts.login.database.get_user_by_username", return_value=konto):
        assert authenticate("max", "geheim123")["id"] == 5


def test_the_wrong_password_returns_nothing():
    konto = {"id": 5, "password_hash": hash_password("geheim123")}
    with patch("src.features.accounts.login.database.get_user_by_username", return_value=konto):
        assert authenticate("max", "falsch") is None


def test_an_unknown_account_returns_nothing():
    with patch("src.features.accounts.login.database.get_user_by_username", return_value=None):
        assert authenticate("gibtsnicht", "geheim123") is None


def test_an_account_without_a_password_cannot_log_in():
    konto = {"id": 5, "password_hash": None}
    with patch("src.features.accounts.login.database.get_user_by_username", return_value=konto):
        assert authenticate("max", "geheim123") is None


def test_a_taken_over_hash_is_replaced_after_a_successful_login():
    konto = {"id": 5, "password_hash": _ssha("altes-passwort")}
    with patch("src.features.accounts.login.database.get_user_by_username", return_value=konto), \
         patch("src.features.accounts.login.database.set_user_password") as setzen:
        assert authenticate("max", "altes-passwort")["id"] == 5

    assert setzen.call_args.args[0] == 5
    assert setzen.call_args.args[1].startswith("$2")


def test_a_bcrypt_hash_is_left_alone():
    konto = {"id": 5, "password_hash": hash_password("geheim123")}
    with patch("src.features.accounts.login.database.get_user_by_username", return_value=konto), \
         patch("src.features.accounts.login.database.set_user_password") as setzen:
        authenticate("max", "geheim123")
    setzen.assert_not_called()


def test_a_failed_login_never_touches_the_hash():
    konto = {"id": 5, "password_hash": _ssha("altes-passwort")}
    with patch("src.features.accounts.login.database.get_user_by_username", return_value=konto), \
         patch("src.features.accounts.login.database.set_user_password") as setzen:
        authenticate("max", "falsch")
    setzen.assert_not_called()


def test_a_long_password_on_an_old_hash_stays_as_it_is():
    # It verifies against SSHA but does not fit into bcrypt, so it must not be rewritten.
    langes = "x" * 100
    konto = {"id": 5, "password_hash": _ssha(langes)}
    with patch("src.features.accounts.login.database.get_user_by_username", return_value=konto), \
         patch("src.features.accounts.login.database.set_user_password") as setzen:
        assert authenticate("max", langes)["id"] == 5
    setzen.assert_not_called()


def test_an_unknown_account_still_costs_one_password_check():
    # Without it the response time alone would tell which names exist.
    with patch("src.features.accounts.login.database.get_user_by_username", return_value=None), \
         patch("src.features.accounts.login.verify_password", return_value=False) as pruefen:
        assert authenticate("gibtsnicht", "geheim123") is None
    pruefen.assert_called_once()
    assert pruefen.call_args.args[1].startswith("$2")


def test_an_account_without_a_password_never_logs_in_through_the_dummy_hash():
    konto = {"id": 5, "password_hash": None}
    with patch("src.features.accounts.login.database.get_user_by_username", return_value=konto), \
         patch("src.features.accounts.login.verify_password", return_value=True):
        assert authenticate("max", "geheim123") is None
