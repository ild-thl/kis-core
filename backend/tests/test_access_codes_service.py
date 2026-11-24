from datetime import datetime, timedelta

from src.features.access_codes.service import (
    new_code,
    new_username,
    normalize_code,
    status_of,
    user_status_of,
)

JETZT = datetime(2026, 8, 28, 12, 0, 0)
SPAETER = JETZT + timedelta(days=1)
FRUEHER = JETZT - timedelta(seconds=1)


def test_new_code_has_the_readable_shape():
    code = new_code()
    assert code.startswith("ASKF-")
    teile = code.split("-")
    assert len(teile) == 3
    assert all(len(teil) == 4 for teil in teile[1:])


def test_new_code_avoids_characters_that_look_alike():
    # Only the two random blocks, the fixed prefix is checked elsewhere.
    zusammen = "".join("".join(new_code().split("-")[1:]) for _ in range(50))
    for zeichen in "01OIL":
        assert zeichen not in zusammen


def test_new_code_is_not_the_same_twice():
    assert new_code() != new_code()


def test_new_username_has_the_right_shape():
    name = new_username()
    assert len(name) == 8
    assert name == name.lower()
    assert name.isalnum()


def test_new_username_avoids_characters_that_look_alike():
    zusammen = "".join(new_username() for _ in range(50))
    for zeichen in "01oil":
        assert zeichen not in zusammen


def test_new_username_is_not_the_same_twice():
    assert new_username() != new_username()


def test_normalize_code_repairs_sloppy_typing():
    assert normalize_code(" askf-4k2p-7rxm ") == "ASKF-4K2P-7RXM"


def test_status_active_when_everything_is_fine():
    assert status_of(
        active=True, used_count=0, max_uses=50, valid_until=SPAETER, now=JETZT
    ) == "active"


def test_status_disabled_beats_everything_else():
    assert status_of(
        active=False, used_count=0, max_uses=50, valid_until=SPAETER, now=JETZT
    ) == "disabled"


def test_status_expired_when_the_deadline_is_past():
    assert status_of(
        active=True, used_count=0, max_uses=50, valid_until=FRUEHER, now=JETZT
    ) == "expired"


def test_status_full_when_every_seat_is_taken():
    assert status_of(
        active=True, used_count=50, max_uses=50, valid_until=SPAETER, now=JETZT
    ) == "full"


def test_user_status_active_when_everything_is_fine():
    assert user_status_of(active=True, access_expires_at=None, now=JETZT) == "active"


def test_user_status_expired_when_the_deadline_is_past():
    assert user_status_of(active=True, access_expires_at=FRUEHER, now=JETZT) == "expired"


def test_user_status_disabled_when_switched_off_before_its_deadline():
    assert user_status_of(active=False, access_expires_at=SPAETER, now=JETZT) == "disabled"


def test_user_status_stays_expired_once_the_lock_job_switches_it_off():
    # The lock job flips active to False once the deadline passes, "expired" must still
    # win over "disabled" here, otherwise an admin can no longer tell the two apart.
    assert user_status_of(active=False, access_expires_at=FRUEHER, now=JETZT) == "expired"
