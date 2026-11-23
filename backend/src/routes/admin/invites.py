"""Create, list and withdraw invitations, until SSO arrives."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from src import database
from src.dependencies_rbac import require_permission
from src.features.invites import repository as repo
from src.features.invites.service import (
    InviteValidationError,
    new_token,
    status_of,
    uid_from_username,
)
from src.i18n import get_locale, t
from src.permissions_registry import PERM_SET_USERS_ALL

router = APIRouter(tags=["admin: invites"])

_require = require_permission(PERM_SET_USERS_ALL)

MAX_DAYS = 30


class CreateInvitePayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    email: str | None = Field(None, max_length=254)
    kis_role: str = Field(..., pattern="^(staff|user|custom)$")
    custom_role_id: int | None = None
    days: int = Field(7, ge=1, le=MAX_DAYS)

    @model_validator(mode="after")
    def _custom_role_id_required_for_custom(self):
        if self.kis_role == "custom" and self.custom_role_id is None:
            raise ValueError("custom_role_id required when kis_role is 'custom'")
        if self.kis_role != "custom":
            self.custom_role_id = None
        return self


@router.post("/invites")
def create_invite(
    payload: CreateInvitePayload,
    admin: dict = Depends(_require),
    locale: str = Depends(get_locale),
):

    try:
        uid = uid_from_username(payload.username)
    except InviteValidationError:
        raise HTTPException(status_code=400, detail=t("invite.noUsableUid", locale))

    # The address is optional now, whoever has none logs in with the user name.
    email = (payload.email or "").strip() or None

    if database.get_user_by_username(uid) is not None:
        raise HTTPException(status_code=409, detail=t("invite.userExists", locale))

    if email is not None:
        if "@" not in email:
            raise HTTPException(status_code=400, detail=t("invite.invalidEmail", locale))
        if database.get_user_by_email(email) is not None:
            raise HTTPException(status_code=409, detail=t("invite.emailExists", locale))

    if repo.open_invite_for_uid(uid) is not None:
        raise HTTPException(status_code=409, detail=t("invite.alreadyInvited", locale))

    if payload.kis_role == "custom" and database.get_custom_role(payload.custom_role_id) is None:
        raise HTTPException(status_code=400, detail=t("invite.invalidCustomRole", locale))

    token = new_token()
    expires_at = datetime.now() + timedelta(days=payload.days)
    invite_id = repo.create_invite(
        token=token,
        email=email,
        uid=uid,
        role=payload.kis_role,
        custom_role_id=payload.custom_role_id,
        created_by=admin.get("user_id", 0),
        expires_at=expires_at,
    )
    return {
        "id": invite_id,
        "token": token,
        "uid": uid,
        "email": email,
        "expires_at": expires_at,
    }


@router.get("/invites")
def list_invites(admin: dict = Depends(_require), locale: str = Depends(get_locale)):
    jetzt = datetime.now()
    return {
        "invites": [
            {
                **{schluessel: eintrag[schluessel] for schluessel in (
                    "id", "email", "uid", "role", "custom_role_id",
                    "token", "created_at", "expires_at", "used_at",
                )},
                "status": status_of(
                    used_at=eintrag["used_at"],
                    expires_at=eintrag["expires_at"],
                    now=jetzt,
                ),
            }
            for eintrag in repo.list_invites()
        ]
    }


@router.delete("/invites/{invite_id}")
def delete_invite(
    invite_id: int,
    admin: dict = Depends(_require),
    locale: str = Depends(get_locale),
):
    if not repo.delete_invite(invite_id):
        raise HTTPException(status_code=404, detail=t("invite.notFound", locale))
    return {"status": "ok"}
