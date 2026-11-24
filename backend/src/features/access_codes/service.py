"""Pure rules around an access code, without database."""
import secrets
from datetime import datetime, timedelta

# No 0, O, 1, I or L, the code gets read out on the phone.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_BLOCK_LENGTH = 4
_USERNAME_LENGTH = 8


def new_code() -> str:
    """A code in the shape KIS-XXXX-XXXX."""
    bloecke = (
        "".join(secrets.choice(_ALPHABET) for _ in range(_BLOCK_LENGTH))
        for _ in range(2)
    )
    return "KIS-" + "-".join(bloecke)


def new_username() -> str:
    """Eight lowercase characters from the same unambiguous alphabet as the code."""
    alphabet = _ALPHABET.lower()
    return "".join(secrets.choice(alphabet) for _ in range(_USERNAME_LENGTH))


def normalize_code(text: str) -> str:
    """What the user typed, in the shape the database holds."""
    return (text or "").strip().upper()


def status_of(
    *,
    active: bool,
    used_count: int,
    max_uses: int,
    valid_until: datetime,
    now: datetime,
) -> str:
    """State of a code: active, disabled, expired or full."""
    if not active:
        return "disabled"
    if valid_until <= now:
        return "expired"
    if used_count >= max_uses:
        return "full"
    return "active"


def user_status_of(*, active: bool, access_expires_at: datetime | None, now: datetime) -> str:
    """State of one account made from a code: disabled, expired or active.

    Expiry wins over the active flag, so an account the lock job switched off
    for running out of time still reads as "expired", not "disabled".
    """
    if access_expires_at and access_expires_at <= now:
        return "expired"
    if not active:
        return "disabled"
    return "active"


def deletion_due_at(*, access_expires_at: datetime | None, grace_days: int) -> datetime | None:
    """When the sweep removes this account, or None while nothing will ever remove it."""
    if access_expires_at is None or grace_days <= 0:
        return None
    return access_expires_at + timedelta(days=grace_days)
