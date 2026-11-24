"""Pure rules around invitations, without database."""
import secrets
from datetime import datetime

from src.features.accounts.uid import slugify_uid


class InviteValidationError(ValueError):
    """The input is not fit for an invitation."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


def uid_from_username(text: str) -> str:
    """Turns what the inviting person typed into a user name the login accepts."""
    uid = slugify_uid(text)
    if uid is None:
        raise InviteValidationError("username", "yields no usable uid")
    return uid


def new_token() -> str:
    """The key in the invitation link, 43 characters from 32 random bytes."""
    return secrets.token_urlsafe(32)


def status_of(*, used_at: datetime | None, expires_at: datetime, now: datetime) -> str:
    """State of an invitation: open, used or expired."""
    if used_at is not None:
        return "used"
    if expires_at <= now:
        return "expired"
    return "open"
