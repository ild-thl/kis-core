"""Admin endpoint to create an account by hand, next to invitation and access code."""
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field, model_validator

from src import database
from src.dependencies_rbac import require_permission
from src.features.accounts.passwords import generate_password
from src.features.accounts.provisioning import provision_account
from src.features.accounts.uid import ist_anmeldename
from src.i18n import get_locale, t
from src.permissions_registry import PERM_SET_USERS_ALL

router = APIRouter(tags=["admin: accounts"])

# Creating users belongs to all users, on top of the server switch.
_require = require_permission(PERM_SET_USERS_ALL)


class CreateAccountPayload(BaseModel):
    uid: str = Field(..., min_length=2, max_length=32)
    given_name: str = Field(..., min_length=1, max_length=64)
    surname: str = Field(..., min_length=1, max_length=64)
    email: str | None = Field(None, max_length=254)
    kis_role: str = Field(..., pattern="^(staff|user|custom)$")
    custom_role_id: int | None = None

    @model_validator(mode="after")
    def _custom_role_id_required_for_custom(self):
        if self.kis_role == "custom" and self.custom_role_id is None:
            raise ValueError("custom_role_id required when kis_role is 'custom'")
        if self.kis_role != "custom" and self.custom_role_id is not None:
            self.custom_role_id = None
        return self


@router.post("/accounts")
def admin_create_account(
    payload: CreateAccountPayload,
    admin: dict = Depends(_require),
    locale: str = Depends(get_locale),
):
    if not ist_anmeldename(payload.uid):
        raise HTTPException(status_code=400, detail=t("admin.ldap.invalidUid", locale))

    email = (payload.email or "").strip() or None
    if email is not None and "@" not in email:
        raise HTTPException(status_code=400, detail=t("admin.ldap.invalidEmail", locale))

    if payload.kis_role == "custom":
        if database.get_custom_role(payload.custom_role_id) is None:
            raise HTTPException(status_code=400, detail=t("admin.ldap.invalidCustomRole", locale))

    if database.get_user_by_username(payload.uid) is not None:
        raise HTTPException(status_code=409, detail=t("admin.ldap.userExists", locale))

    if email is not None and database.get_user_by_email(email) is not None:
        raise HTTPException(status_code=409, detail=t("admin.ldap.userExists", locale))

    password = generate_password()
    try:
        provision_account(
            uid=payload.uid,
            given_name=payload.given_name,
            surname=payload.surname,
            email=email,
            role=payload.kis_role,
            custom_role_id=payload.custom_role_id,
            password=password,
        )
    except Exception as e:
        logger.error("account creation failed for uid={}: {}", payload.uid, e)
        raise HTTPException(status_code=500, detail=t("admin.ldap.addFailed", locale))

    logger.info(
        "admin {} created account uid={} role={}",
        admin.get("email"),
        payload.uid,
        payload.kis_role,
    )
    return {"uid": payload.uid, "generated_password": password}
