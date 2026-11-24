"""Slip into somebody else's account to see a reported problem first hand."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from loguru import logger

from src import database
from src.dependencies import get_current_user, get_session_store, get_settings
from src.dependencies_rbac import require_permission
from src.features.impersonation import repository as repo
from src.features.impersonation import service
from src.i18n import get_locale, t
from src.permissions_registry import PERM_SET_USERS_IMPERSONATE
from src.routes._shared import set_session_cookie

router = APIRouter(tags=["admin: impersonation"])

_require = require_permission(PERM_SET_USERS_IMPERSONATE)

@router.post("/users/{user_id}/impersonate")
def start_impersonation(
    user_id: int,
    request: Request,
    response: Response,
    actor: dict = Depends(_require),
    locale: str = Depends(get_locale),
):
    """Hands the caller a session of the target account and keeps their own."""
    settings = get_settings()
    if settings.is_local_mode:
        raise HTTPException(status_code=409, detail=t("impersonation.ownSessionGone", locale))

    parent_token = request.cookies.get("session")
    if not parent_token:
        raise HTTPException(status_code=409, detail=t("impersonation.ownSessionGone", locale))

    target = database.get_user_by_id(user_id)
    target = dict(target) if target else None
    grund = service.refusal_key(actor=actor, target=target, admin_email=settings.admin_email)
    if grund == "impersonation.userNotFound":
        raise HTTPException(status_code=404, detail=t(grund, locale))
    if grund:
        raise HTTPException(status_code=403, detail=t(grund, locale))

    log_id = repo.start_entry(
        actor_user_id=actor.get("user_id"),
        actor_username=actor.get("username") or "",
        target_user_id=target["id"],
        target_username=target["username"],
    )
    store = get_session_store()
    token = store.create(
        data=service.session_payload(target, actor, log_id, parent_token)
    )
    set_session_cookie(response, token)
    logger.info(
        "Impersonation started: {} -> {} (log {})",
        actor.get("username"), target["username"], log_id,
    )
    return {
        "status": "ok",
        "user_id": target["id"],
        "display_name": target.get("display_name") or target["username"],
    }


@router.post("/impersonation/stop")
def stop_impersonation(
    request: Request,
    response: Response,
    user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    """Gives the caller their own session back. No permission gate on purpose:
    during an impersonation the session carries the rights of the target."""
    if not service.is_impersonating(user):
        raise HTTPException(status_code=409, detail=t("impersonation.notActive", locale))

    marke = user.get(service.SESSION_KEY) or {}
    log_id = marke.get("log_id")
    if log_id:
        repo.end_entry(int(log_id), "manual")

    store = get_session_store()
    current = request.cookies.get("session")
    parent_token = user.get(service.SESSION_PARENT_TOKEN)
    # Check the way back before dropping the borrowed session, order matters here.
    zurueck = bool(parent_token) and store.validate(parent_token)
    if current and current != parent_token:
        store.destroy(current)

    if not zurueck:
        response.delete_cookie("session")
        raise HTTPException(status_code=409, detail=t("impersonation.ownSessionGone", locale))

    set_session_cookie(response, parent_token)
    logger.info("Impersonation ended: back to {}", marke.get("username"))
    return {"status": "ok", "display_name": marke.get("display_name")}


@router.get("/impersonation/log")
def read_log(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _actor: dict = Depends(_require),
):
    """The record for the admin area, newest first."""
    return {
        "entries": repo.list_entries(limit=limit, offset=offset),
        "total": repo.count_entries(),
    }
