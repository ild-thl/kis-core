from datetime import datetime, timedelta

import pytest

from src.features.invites.service import (
    InviteValidationError,
    new_token,
    status_of,
    uid_from_username,
)


def test_uid_from_username_keeps_what_was_typed():
    assert uid_from_username("max.mustermann") == "max.mustermann"


def test_uid_from_username_normalizes_case_and_umlauts():
    assert uid_from_username("Jörg.Müller") == "joerg.mueller"


def test_uid_from_username_drops_characters_a_login_name_does_not_accept():
    assert uid_from_username("anna+test") == "annatest"


def test_uid_from_username_turns_a_full_name_into_one_word():
    assert uid_from_username("Anna Beispiel") == "anna-beispiel"


@pytest.mark.parametrize("eingabe", ["!", "a", "+++"])
def test_uid_from_username_rejects_what_is_left_unusable(eingabe):
    with pytest.raises(InviteValidationError):
        uid_from_username(eingabe)


def test_new_token_is_long_and_unique():
    erster, zweiter = new_token(), new_token()
    assert len(erster) >= 32
    assert erster != zweiter


JETZT = datetime(2026, 8, 25, 12, 0, 0)


def test_status_open_when_unused_and_not_expired():
    assert status_of(used_at=None, expires_at=JETZT + timedelta(days=1), now=JETZT) == "open"


def test_status_expired_when_valid_until_is_past():
    assert status_of(used_at=None, expires_at=JETZT - timedelta(seconds=1), now=JETZT) == "expired"


def test_status_used_wins_over_expired():
    assert status_of(
        used_at=JETZT - timedelta(days=2),
        expires_at=JETZT - timedelta(days=1),
        now=JETZT,
    ) == "used"
