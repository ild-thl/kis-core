"""Quota management: global defaults, per-user overview, and per-type overrides."""

from fastapi import APIRouter, Depends, HTTPException

from src import database as db
from src.i18n import get_locale, t
from src.limits import QUOTA_DEFAULTS

from src.routes.admin._models import SetQuotaOverrideRequest

from src.dependencies_rbac import require_permission
from src.permissions_registry import PERM_SET_USERS_ALL

router = APIRouter(tags=["admin: quota"])

# Quotas are a jump-off from all users and share its right.
_require = require_permission(PERM_SET_USERS_ALL)


def _iso_z(ts) -> str | None:
    return (ts.isoformat() + "Z") if ts else None


def _entry(quota_type: str, cfg: dict, row: dict | None) -> dict:
    """One quota as the admin page shows it, without a row the person has not used it yet."""
    override = row["override"] if row else None
    # A type that left the defaults keeps the old fallback of 30.
    limit = override if override is not None else cfg.get("limit", 30)
    return {
        "quota_type": quota_type,
        "label": cfg.get("label", quota_type),
        "used": row["used"] if row else 0,
        "limit": limit,
        "limit_is_unlimited": limit == -1,
        "override": override,
        "reset_at": _iso_z(row["reset_at"]) if row else None,
    }


def _ensure_known_quota_type(quota_type: str, locale: str) -> None:
    if quota_type not in QUOTA_DEFAULTS:
        raise HTTPException(
            status_code=400,
            detail=t("admin.quota.unknownType", locale, quota_type=quota_type),
        )


@router.get("/quota/defaults")
def get_quota_defaults(_admin=Depends(_require)):
    """Show global default limits."""
    return {"defaults": QUOTA_DEFAULTS}


@router.get("/quota/overview")
def get_quota_overview(_admin=Depends(_require)):
    """All active users with their quotas (even without prior activity)."""
    rows = db.quota_get_all_users_usage()
    users: dict[int, dict] = {}
    for row in rows:
        uid = row["user_id"]
        if uid not in users:
            users[uid] = {
                "user_id": uid,
                "username": row["username"],
                "display_name": row["display_name"],
                "quotas": [],
            }
        if row["quota_type"] is None:
            # User exists but has no quota entries yet - fill from QUOTA_DEFAULTS
            users[uid]["quotas"].extend(_entry(cfg_type, cfg, None) for cfg_type, cfg in QUOTA_DEFAULTS.items())
        else:
            cfg = QUOTA_DEFAULTS.get(row["quota_type"], {})
            users[uid]["quotas"].append(_entry(row["quota_type"], cfg, row))
    return {"users": list(users.values())}


@router.get("/quota/users/{user_id}")
def get_user_quota(user_id: int, _admin=Depends(_require)):
    """All quota types for a specific user."""
    rows = db.quota_get_all_for_user(user_id)
    by_type = {r["quota_type"]: r for r in reversed(rows)}
    return {
        "user_id": user_id,
        "quotas": [_entry(cfg_type, cfg, by_type.get(cfg_type)) for cfg_type, cfg in QUOTA_DEFAULTS.items()],
    }


@router.post("/quota/users/{user_id}/{quota_type}/override")
def set_quota_override(
    user_id: int,
    quota_type: str,
    body: SetQuotaOverrideRequest,
    _admin=Depends(_require),
    locale: str = Depends(get_locale),
):
    """Set per-user limit. -1 = unlimited."""
    _ensure_known_quota_type(quota_type, locale)
    db.quota_set_override(user_id, quota_type, body.limit_value)
    return {"ok": True}


@router.delete("/quota/users/{user_id}/{quota_type}/override")
def delete_quota_override(
    user_id: int,
    quota_type: str,
    _admin=Depends(_require),
    locale: str = Depends(get_locale),
):
    """Delete override - user falls back to the global default."""
    _ensure_known_quota_type(quota_type, locale)
    db.quota_remove_override(user_id, quota_type)
    return {"ok": True}


@router.post("/quota/users/{user_id}/{quota_type}/reset")
def reset_user_quota(
    user_id: int,
    quota_type: str,
    _admin=Depends(_require),
    locale: str = Depends(get_locale),
):
    """Reset quota counter to 0 immediately and end its window."""
    _ensure_known_quota_type(quota_type, locale)
    db.quota_reset(user_id, quota_type)
    return {"ok": True}
