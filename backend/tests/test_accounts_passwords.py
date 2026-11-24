"""Hashing for the database login, bcrypt for new hashes, SSHA only for the old ones."""

import base64
import hashlib
import os

import pytest

from src.features.accounts.passwords import (
    MAX_PASSWORD_BYTES,
    PasswordTooLongError,
    hash_password,
    needs_rehash,
    verify_password,
)


def _ssha(password: str) -> str:
    """Builds a salted SHA-1 hash in the taken over format, for the upgrade tests."""
    salt = os.urandom(4)
    digest = hashlib.sha1(password.encode("utf-8") + salt).digest()
    return "{SSHA}" + base64.b64encode(digest + salt).decode("ascii")


def test_a_fresh_hash_is_bcrypt_and_verifies():
    hash_wert = hash_password("geheim123")
    assert hash_wert.startswith("$2")
    assert verify_password("geheim123", hash_wert) is True


def test_the_wrong_password_does_not_verify():
    assert verify_password("falsch", hash_password("geheim123")) is False


def test_two_hashes_of_the_same_password_differ():
    assert hash_password("geheim123") != hash_password("geheim123")


def test_a_taken_over_ssha_hash_still_verifies():
    assert verify_password("altes-passwort", _ssha("altes-passwort")) is True


def test_a_wrong_password_against_ssha_does_not_verify():
    assert verify_password("falsch", _ssha("altes-passwort")) is False


def test_only_ssha_asks_for_a_rehash():
    assert needs_rehash(_ssha("egal")) is True
    assert needs_rehash(hash_password("egal")) is False


def test_no_hash_at_all_never_verifies():
    assert verify_password("geheim123", None) is False
    assert verify_password("geheim123", "") is False
    assert needs_rehash(None) is False


def test_an_empty_password_never_verifies():
    assert verify_password("", hash_password("geheim123")) is False


def test_rubbish_in_the_column_does_not_blow_up():
    assert verify_password("geheim123", "kein-hash") is False
    assert verify_password("geheim123", "{SSHA}nicht-base64!!") is False


def test_a_password_beyond_the_limit_is_refused_instead_of_cut():
    with pytest.raises(PasswordTooLongError):
        hash_password("x" * (MAX_PASSWORD_BYTES + 1))


def test_the_limit_counts_bytes_not_characters():
    # Each umlaut is two bytes in UTF-8, so 37 of them are over the line.
    with pytest.raises(PasswordTooLongError):
        hash_password("ä" * 37)


def test_a_password_beyond_the_limit_cannot_verify_against_bcrypt():
    assert verify_password("x" * (MAX_PASSWORD_BYTES + 1), hash_password("kurz")) is False


def test_a_long_password_still_works_against_ssha():
    # SSHA has no limit, such an account may exist and must not be locked out.
    langes = "x" * 100
    assert verify_password(langes, _ssha(langes)) is True


def test_the_ssha_digest_is_compared_in_constant_time(monkeypatch):
    import hmac

    from src.features.accounts import passwords

    gesehen = []
    echt = hmac.compare_digest

    def _vergleich(a, b):
        gesehen.append((a, b))
        return echt(a, b)

    monkeypatch.setattr(passwords.hmac, "compare_digest", _vergleich)
    assert verify_password("altes-passwort", _ssha("altes-passwort")) is True
    assert len(gesehen) == 1
