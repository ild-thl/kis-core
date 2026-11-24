from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from loguru import logger
from pydantic import BaseModel

from src import database
from src.dependencies import get_settings, get_session_store
from src.features.accounts.demo_onboarding import demo_module_zuweisen
from src.features.impersonation import repository as impersonation_repo
from src.features.impersonation import service as impersonation
from src.i18n import get_locale, t
from src.features.accounts.login import authenticate
from src.modules import active_modules
from src.routes._shared import set_session_cookie
from src.security.auth import ACCESS_EXPIRED, access_expired_error
from src.services.consent import has_global_consent

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginRequest, response: Response, locale: str = Depends(get_locale)):
    settings = get_settings()

    # Step 1: The password lives in the database, the field takes a name or a mail address.
    db_user = authenticate(body.username, body.password)
    if db_user is None:
        logger.warning("Failed login attempt for '{}' (invalid credentials)", body.username)
        raise HTTPException(status_code=401, detail=t("auth.invalidCredentials", locale))

    username = db_user["username"]
    display_name = db_user["display_name"] or username
    email = db_user["email"] or None
    user_id = db_user["id"]
    effective_role = db_user["role"] or "user"
    custom_role_id = db_user["custom_role_id"]
    active = db_user["active"]

    # During maintenance only an admin may log in.
    maintenance_on = database.get_setting("maintenance_mode", "false").lower() == "true"
    is_admin_email = bool(email and settings.admin_email and email.lower() == settings.admin_email.lower())
    is_db_admin = effective_role == "admin"
    if maintenance_on and not (is_admin_email or is_db_admin):
        logger.warning("Login blocked for '{}' (maintenance active, non-admin)", username)
        raise HTTPException(status_code=503, detail=t("maintenance.message", locale))

    # Step 2: The column decides, the whitelist only writes into it.
    if not active:
        logger.warning("Login blocked for '{}' (not activated)", username)
        raise HTTPException(status_code=403, detail="account_not_activated")

    # Step 3: A test access whose deadline has passed gets no session.
    ablauf = db_user["access_expires_at"]
    if ablauf is not None:
        try:
            abgelaufen = ablauf <= datetime.now()
        except (TypeError, ValueError) as e:
            logger.error("Unparseable access_expires_at '{}' for '{}': {}", ablauf, username, e)
            ablauf = None
        else:
            if abgelaufen:
                logger.info("Login blocked for '{}' (test access expired)", username)
                raise access_expired_error()

    # Step 4: The demo module, once per account, whichever way it was created.
    demo_module_zuweisen(user_id)

    # Step 5: Create session
    store = get_session_store()
    token = store.create(data={
        "user_id": user_id,
        "username": username,
        "display_name": display_name,
        "email": email or "",
        "role": effective_role,
        "custom_role_id": custom_role_id,
        "access_expires_at": ablauf.isoformat() if ablauf else None,
    })
    set_session_cookie(response, token)
    return {"status": "ok", "username": username, "display_name": display_name, "role": effective_role}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("session")
    if token:
        store = get_session_store()
        data = store.get_data(token) or {}
        _close_impersonation(store, data)
        store.destroy(token)
    response.delete_cookie("session")
    return {"status": "ok"}


def _close_impersonation(store, data: dict) -> None:
    """Logging out of a borrowed account closes the record and the own session."""
    marke = data.get(impersonation.SESSION_KEY)
    if not marke:
        return
    log_id = marke.get("log_id")
    if log_id:
        try:
            impersonation_repo.end_entry(int(log_id), "logout")
        except Exception as e:
            logger.error("Could not close impersonation record {}: {}", log_id, e)
    parent = data.get(impersonation.SESSION_PARENT_TOKEN)
    if parent:
        store.destroy(parent)


def _permissions_payload(perms) -> dict:
    """The rights as the frontend reads them, the full key set decides per page in the sidebar."""
    return {
        "allow_admin_panel": perms.allow_admin_panel,
        "allow_aia": perms.allow_aia,
        "allow_workspace_create": perms.allow_workspace_create,
        "allow_account_create": perms.allow_account_create,
        "tools": list(perms.tools),
        "keys": sorted(perms.keys),
    }


@router.get("/status")
def auth_status(request: Request):
    settings = get_settings()

    if settings.is_local_mode:
        from src.permissions import resolve_user_permissions
        local_user = database.get_user_by_username("local")
        user_id = local_user["id"] if local_user else 0
        perms = resolve_user_permissions(role="admin", custom_role_id=None, is_env_admin=True)
        return {
            "authenticated": True,
            "local_mode": True,
            "is_admin": True,
            "role": "admin",
            "custom_role_id": None,
            "user_id": user_id,
            "username": "local",
            "display_name": "Admin",
            "email": "",
            "global_consent_accepted": has_global_consent(user_id),
            "permissions": _permissions_payload(perms),
            "modules": sorted(active_modules()),
        }

    token = request.cookies.get("session")
    if not token:
        return {"authenticated": False}
    store = get_session_store()
    if not store.validate(token):
        return {"authenticated": False}
    data = store.get_data(token) or {}
    email = (data.get("email") or "").lower()
    is_env_admin = bool(email and settings.admin_email and email == settings.admin_email.lower())

    # Always re-fetch role from DB so role changes apply on next request, not next login.
    user_id = data.get("user_id")
    if user_id:
        db_user = database.get_user_by_id(user_id)
        if db_user:
            ablauf = db_user.get("access_expires_at")
            if ablauf is not None:
                try:
                    expired = ablauf <= datetime.now()
                except (TypeError, ValueError) as e:
                    logger.error("Unparseable access_expires_at '{}' for user {}: {}", ablauf, user_id, e)
                    expired = False
                if expired:
                    # The reason travels along so the login page can say what happened.
                    return {"authenticated": False, "reason": ACCESS_EXPIRED}
            # The deadline comes from the account, so an extension by the admin shows at once.
            data["access_expires_at"] = ablauf.isoformat() if isinstance(ablauf, datetime) else None
            data["role"] = db_user.get("role") or data.get("role") or "user"
            data["custom_role_id"] = db_user.get("custom_role_id")

    from src.permissions import resolve_user_permissions
    perms = resolve_user_permissions(
        role=data.get("role", "user"),
        custom_role_id=data.get("custom_role_id"),
        is_env_admin=is_env_admin,
    )
    payload = {
        "authenticated": True,
        "is_admin": perms.allow_admin_panel,
        "role": data.get("role", "user"),
        "custom_role_id": data.get("custom_role_id"),
        "permissions": _permissions_payload(perms),
        "modules": sorted(active_modules()),
        "global_consent_accepted": has_global_consent(user_id) if user_id else False,
    }
    # Preserve other session fields (display_name, username, etc.) without clobbering keys above.
    # The token of the borrowed session stays on the server, it must never reach a browser.
    for k, v in data.items():
        if k not in payload and k != impersonation.SESSION_PARENT_TOKEN:
            payload[k] = v
    return payload
