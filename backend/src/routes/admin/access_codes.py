"""Create, list, switch off and delete access codes for test rounds."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field, model_validator

from src import database
from src.dependencies import get_settings
from src.dependencies_rbac import assert_may_grant, permissions_of, require_permission
from src.features.access_codes import repository as repo
from src.features.access_codes.accounts import delete_accounts, lock_accounts
from src.features.access_codes.retention import grace_period_days
from src.features.access_codes.service import (
    deletion_due_at,
    new_code,
    status_of,
    user_status_of,
)
from src.features.accounts.passwords import generate_password, hash_password
from src.i18n import get_locale, t
from src.permissions_registry import PERM_AIA_WORKSPACE_CREATE, PERM_SET_USERS_ALL, SYSTEM_ROLE_PERMISSIONS

router = APIRouter(tags=["admin: access codes"])

_require = require_permission(PERM_SET_USERS_ALL)

MAX_VALID_DAYS = 365
MAX_ACCESS_HOURS = 720  # 30 Tage
MAX_SEATS = 500
MAX_WORKSPACES = 50
MAX_OWNER_HITS = 20


class CreateCodePayload(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
    max_uses: int = Field(50, ge=1, le=MAX_SEATS)
    valid_days: int = Field(30, ge=1, le=MAX_VALID_DAYS)
    access_hours: int | None = Field(336)
    show_credentials: bool = True
    show_evaluation: bool = False
    kis_role: str = Field("user", pattern="^(staff|user|custom)$")
    custom_role_id: int | None = None
    workspace_ids: list[int] = Field(default_factory=list, max_length=MAX_WORKSPACES)

    @model_validator(mode="after")
    def _label_and_role(self):
        if not self.label.strip():
            raise ValueError("label must not be blank")
        self.label = self.label.strip()
        if self.access_hours is not None and not (1 <= self.access_hours <= MAX_ACCESS_HOURS):
            raise ValueError(f"access_hours must be between 1 and {MAX_ACCESS_HOURS}")
        if self.kis_role == "custom" and self.custom_role_id is None:
            raise ValueError("custom_role_id required when kis_role is 'custom'")
        if self.kis_role != "custom":
            self.custom_role_id = None
        return self


class PatchCodePayload(BaseModel):
    active: bool | None = None
    label: str | None = Field(None, min_length=1, max_length=64)
    max_uses: int | None = Field(None, ge=1, le=MAX_SEATS)
    valid_days: int | None = Field(None, ge=1, le=MAX_VALID_DAYS)
    access_hours: int | None = None
    show_credentials: bool = True
    show_evaluation: bool = False
    kis_role: str | None = Field(None, pattern="^(staff|user|custom)$")
    custom_role_id: int | None = None
    # None leaves the workspaces as they are.
    workspace_ids: list[int] | None = Field(None, max_length=MAX_WORKSPACES)

    @model_validator(mode="after")
    def _edit_fields_travel_together(self):
        bearbeitungsfelder = (self.label, self.max_uses, self.valid_days, self.kis_role)
        if any(f is not None for f in bearbeitungsfelder) and not all(f is not None for f in bearbeitungsfelder):
            raise ValueError("label, max_uses, valid_days and kis_role must be provided together")
        if self.label is not None:
            if not self.label.strip():
                raise ValueError("label must not be blank")
            self.label = self.label.strip()
        if self.access_hours is not None and not (1 <= self.access_hours <= MAX_ACCESS_HOURS):
            raise ValueError(f"access_hours must be between 1 and {MAX_ACCESS_HOURS}")
        if self.kis_role == "custom" and self.custom_role_id is None:
            raise ValueError("custom_role_id required when kis_role is 'custom'")
        if self.kis_role is not None and self.kis_role != "custom":
            self.custom_role_id = None
        return self


def _assert_may_hand_out(admin: dict, role: str, custom_role_id: int | None, locale: str) -> None:
    """A code may only carry a role that exists and that its creator could grant by hand."""
    if role == "custom":
        role_row = database.get_custom_role(custom_role_id)
        if role_row is None:
            raise HTTPException(status_code=400, detail=t("access.invalidCustomRole", locale))
        granted = role_row["permissions"]
    else:
        granted = SYSTEM_ROLE_PERMISSIONS.get(role, ())
    assert_may_grant(permissions_of(admin), granted, locale)


@router.post("/access-codes")
def create_access_code(
    payload: CreateCodePayload,
    admin: dict = Depends(_require),
    locale: str = Depends(get_locale),
):

    _assert_may_hand_out(admin, payload.kis_role, payload.custom_role_id, locale)

    code = new_code()
    valid_until = datetime.now() + timedelta(days=payload.valid_days)
    code_id = repo.create_code(
        code=code,
        label=payload.label,
        role=payload.kis_role,
        custom_role_id=payload.custom_role_id,
        max_uses=payload.max_uses,
        valid_until=valid_until,
        access_hours=payload.access_hours,
        show_credentials=payload.show_credentials,
        show_evaluation=payload.show_evaluation,
        created_by=admin.get("user_id", 0),
    )
    if payload.workspace_ids:
        repo.set_code_workspaces(code_id, payload.workspace_ids)
    return {
        "id": code_id,
        "code": code,
        "label": payload.label,
        "max_uses": payload.max_uses,
        "valid_until": valid_until,
        "access_hours": payload.access_hours,
        "show_credentials": payload.show_credentials,
        "show_evaluation": payload.show_evaluation,
    }


@router.get("/access-codes")
def list_access_codes(admin: dict = Depends(_require), locale: str = Depends(get_locale)):
    jetzt = datetime.now()
    workspaces = repo.workspaces_by_code()
    return {
        "codes": [
            {
                **{schluessel: eintrag[schluessel] for schluessel in (
                    "id", "code", "label", "role", "custom_role_id", "max_uses",
                    "used_count", "valid_until", "access_hours", "show_credentials",
                    "show_evaluation", "active", "created_at",
                )},
                "status": status_of(
                    active=eintrag["active"],
                    used_count=eintrag["used_count"],
                    max_uses=eintrag["max_uses"],
                    valid_until=eintrag["valid_until"],
                    now=jetzt,
                ),
                "workspaces": workspaces.get(eintrag["id"], []),
            }
            for eintrag in repo.list_codes()
        ]
    }


@router.get("/access-codes/workspace-owners")
def list_access_code_workspace_owners(
    q: str = Query("", max_length=64),
    user_ids: list[int] = Query(default_factory=list, max_length=MAX_WORKSPACES),
    admin: dict = Depends(_require),
    locale: str = Depends(get_locale),
):
    """People who may create workspaces and own some, found by search or by id, never the whole list."""
    suche = q.strip()
    if not suche and not user_ids:
        return {"owners": []}
    return {"owners": repo.search_workspace_owners(
        query=suche,
        user_ids=user_ids,
        system_roles=[r for r, rechte in SYSTEM_ROLE_PERMISSIONS.items() if PERM_AIA_WORKSPACE_CREATE in rechte],
        custom_role_ids=repo.custom_role_ids_with(PERM_AIA_WORKSPACE_CREATE),
        admin_email=(get_settings().admin_email or "").strip().lower(),
        limit=MAX_OWNER_HITS,
    )}


@router.patch("/access-codes/{code_id}")
def patch_access_code(
    code_id: int,
    payload: PatchCodePayload,
    admin: dict = Depends(_require),
    locale: str = Depends(get_locale),
):

    if payload.active is not None:
        if not repo.set_active(code_id, payload.active):
            raise HTTPException(status_code=404, detail=t("access.notFound", locale))

    if payload.label is not None:
        if repo.get_code_by_id(code_id) is None:
            raise HTTPException(status_code=404, detail=t("access.notFound", locale))

        _assert_may_hand_out(admin, payload.kis_role, payload.custom_role_id, locale)

        valid_until = datetime.now() + timedelta(days=payload.valid_days)
        if not repo.update_code(
            code_id,
            label=payload.label,
            role=payload.kis_role,
            custom_role_id=payload.custom_role_id,
            max_uses=payload.max_uses,
            valid_until=valid_until,
            access_hours=payload.access_hours,
            show_credentials=payload.show_credentials,
            show_evaluation=payload.show_evaluation,
        ):
            raise HTTPException(status_code=400, detail=t("access.maxUsesBelowUsed", locale))

    if payload.workspace_ids is not None:
        if repo.get_code_by_id(code_id) is None:
            raise HTTPException(status_code=404, detail=t("access.notFound", locale))
        repo.set_code_workspaces(code_id, payload.workspace_ids)
        # Accounts that came in earlier join the newly added workspaces too, nobody is taken out.
        neu = repo.enroll_into_code_workspaces(code_id, repo.list_user_ids_for_code(code_id))
        if neu:
            logger.info("access code {} enrolled {} earlier accounts into its workspaces", code_id, neu)

    return {"status": "ok"}


@router.delete("/access-codes/{code_id}")
def delete_access_code(
    code_id: int,
    admin: dict = Depends(_require),
    locale: str = Depends(get_locale),
):
    """Removes only the code, every account it created stays."""
    if not repo.delete_code(code_id):
        raise HTTPException(status_code=404, detail=t("access.notFound", locale))
    return {"status": "ok"}


@router.get("/access-codes/{code_id}/users")
def list_access_code_users(
    code_id: int,
    admin: dict = Depends(_require),
    locale: str = Depends(get_locale),
):
    return {"users": _with_status(repo.list_users_for_code(code_id))}


def _with_status(eintraege: list[dict]) -> list[dict]:
    """Adds the account state and the planned deletion date to each row."""
    jetzt = datetime.now()
    frist = grace_period_days()
    return [
        {
            **eintrag,
            "status": user_status_of(
                active=eintrag["active"],
                access_expires_at=eintrag["access_expires_at"],
                now=jetzt,
            ),
            "delete_at": deletion_due_at(
                access_expires_at=eintrag["access_expires_at"],
                grace_days=frist,
            ),
        }
        for eintrag in eintraege
    ]


class BulkUsersPayload(BaseModel):
    action: str = Field(..., pattern="^(lock|delete)$")
    code_id: int


@router.post("/access-codes/users/bulk")
def bulk_access_code_users(
    payload: BulkUsersPayload,
    admin: dict = Depends(_require),
    locale: str = Depends(get_locale),
):
    """Locks or deletes every account one code created."""
    if repo.get_code_by_id(payload.code_id) is None:
        raise HTTPException(status_code=404, detail=t("access.notFound", locale))
    user_ids = repo.list_user_ids_for_code(payload.code_id)

    if payload.action == "lock":
        anzahl = lock_accounts(user_ids)
    else:
        anzahl = delete_accounts(user_ids)
    logger.info(
        "admin {} ran {} on {} code accounts (code_id={})",
        admin.get("email"), payload.action, anzahl, payload.code_id,
    )
    return {"status": "ok", "count": anzahl}


def _code_account(user_id: int, locale: str) -> dict:
    """The account, but only one a code created, never a real staff or admin account."""
    konto = database.get_user_by_id(user_id)
    if not konto or not konto.get("access_code_id"):
        raise HTTPException(status_code=403, detail=t("access.notFromCode", locale))
    return konto


class UserActivePayload(BaseModel):
    active: bool


@router.patch("/access-codes/users/{user_id}")
def set_access_code_user_active(
    user_id: int,
    payload: UserActivePayload,
    admin: dict = Depends(_require),
    locale: str = Depends(get_locale),
):
    """Switches the login of one code account on or off."""
    _code_account(user_id, locale)
    if payload.active:
        repo.set_users_active([user_id], True)
    else:
        lock_accounts([user_id])
    return {"status": "ok"}


@router.delete("/access-codes/users/{user_id}")
def delete_access_code_user(
    user_id: int,
    admin: dict = Depends(_require),
    locale: str = Depends(get_locale),
):
    """Removes one code account with everything it owns."""
    _code_account(user_id, locale)
    if not delete_accounts([user_id]):
        raise HTTPException(status_code=500, detail=t("access.deleteAccountFailed", locale))
    logger.info("admin {} deleted code account user_id={}", admin.get("email"), user_id)
    return {"status": "ok"}


@router.post("/access-codes/users/{user_id}/password")
def reset_access_code_user_password(
    user_id: int,
    admin: dict = Depends(_require),
    locale: str = Depends(get_locale),
):
    """Gives an account made from a code a brand new password, never a real staff or admin account."""
    konto = _code_account(user_id, locale)

    password = generate_password()
    try:
        database.set_user_password(user_id, hash_password(password))
    except Exception as e:
        logger.error("password reset failed for user_id={}: {}", user_id, e)
        raise HTTPException(status_code=500, detail=t("access.passwordResetFailed", locale))

    logger.info("admin {} reset the password for user_id={}", admin.get("email"), user_id)
    return {"username": konto["username"], "password": password}


@router.get("/access-codes/users/{user_id}/activity")
def access_code_user_activity(
    user_id: int,
    admin: dict = Depends(_require),
    locale: str = Depends(get_locale),
):
    """Read-only look at a test account's modules and chat history, never for a real account."""
    _code_account(user_id, locale)

    return {
        "workspaces": repo.list_workspaces_for_user(user_id),
        "messages": repo.list_messages_for_user(user_id),
    }
