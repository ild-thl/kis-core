"""The rules for slipping into somebody else's account."""

from datetime import datetime

from src.permissions import resolve_user_permissions
from src.permissions_registry import SET_USER_KEYS

# The session field the whole feature hangs on, visible to the interface.
SESSION_KEY = "impersonator"
# The key of the caller's own session, it must never leave the server.
SESSION_PARENT_TOKEN = "impersonator_token"

# Holding one of these means the account could hand out rights, so it stays closed.
FORBIDDEN_TARGET_KEYS: frozenset[str] = frozenset(SET_USER_KEYS)


def is_impersonating(session: dict) -> bool:
    return bool(session.get(SESSION_KEY))


def target_permissions(target: dict, admin_email: str | None):
    """Effective rights of the target account, custom roles included."""
    email = (target.get("email") or "").lower()
    is_env_admin = bool(admin_email and email == admin_email.lower())
    return resolve_user_permissions(
        role=target.get("role") or "user",
        custom_role_id=target.get("custom_role_id"),
        is_env_admin=is_env_admin,
    )


def refusal_key(
    *,
    actor: dict,
    target: dict | None,
    admin_email: str | None,
    now: datetime | None = None,
) -> str | None:
    """The reason why this account stays closed, or None when it may be entered."""
    if is_impersonating(actor):
        return "impersonation.nested"
    if target is None:
        return "impersonation.userNotFound"
    if int(target.get("id") or 0) == int(actor.get("user_id") or 0):
        return "impersonation.self"

    email = (target.get("email") or "").lower()
    if admin_email and email == admin_email.lower():
        return "impersonation.targetIsAdmin"
    if (target.get("role") or "") == "admin":
        return "impersonation.targetIsAdmin"
    if target_permissions(target, admin_email).has(*FORBIDDEN_TARGET_KEYS):
        return "impersonation.targetIsAdmin"

    if not target.get("active"):
        return "impersonation.targetInactive"

    expires = target.get("access_expires_at")
    if isinstance(expires, datetime) and expires <= (now or datetime.now()):
        return "impersonation.targetExpired"
    return None


def session_payload(target: dict, actor: dict, log_id: int, parent_token: str) -> dict:
    """The session of the target, shaped exactly like a real login."""
    expires = target.get("access_expires_at")
    return {
        "user_id": target["id"],
        "username": target["username"],
        "display_name": target.get("display_name") or target["username"],
        "email": target.get("email") or "",
        "role": target.get("role") or "user",
        "custom_role_id": target.get("custom_role_id"),
        "access_expires_at": expires.isoformat() if isinstance(expires, datetime) else None,
        SESSION_KEY: {
            "user_id": actor.get("user_id"),
            "username": actor.get("username"),
            "display_name": actor.get("display_name") or actor.get("username"),
            "log_id": log_id,
        },
        SESSION_PARENT_TOKEN: parent_token,
    }
