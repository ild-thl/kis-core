"""The public page of an invitation, the key in the link is the credential."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from loguru import logger
from pydantic import BaseModel, Field

from src.dependencies import get_session_store
from src.features.accounts.demo_onboarding import demo_module_zuweisen
from src.features.accounts.provisioning import provision_account
from src.features.invites import repository as repo
from src.features.invites.service import status_of
from src.i18n import get_locale, t
from src.routes._shared import MIN_PASSWORD_LENGTH, set_session_cookie

router = APIRouter(prefix="/invites", tags=["invites"])


def _open_invite_or_error(token: str, locale: str) -> dict:
    """Fetches the invitation and lets only an open one through."""
    invite = repo.get_invite_by_token(token)
    if invite is None:
        raise HTTPException(status_code=404, detail=t("invite.notFound", locale))

    zustand = status_of(
        used_at=invite["used_at"], expires_at=invite["expires_at"], now=datetime.now()
    )
    if zustand != "open":
        raise HTTPException(status_code=410, detail=t("invite.notValid", locale))
    return invite


@router.get("/{token}")
def read_invite(token: str, locale: str = Depends(get_locale)):
    invite = _open_invite_or_error(token, locale)
    # The address is made up, only the user name is worth showing.
    return {"uid": invite["uid"]}


class RedeemPayload(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)
    given_name: str = Field("", max_length=64)
    surname: str = Field("", max_length=64)


@router.post("/{token}")
def redeem_invite(
    token: str,
    payload: RedeemPayload,
    response: Response,
    locale: str = Depends(get_locale),
):
    invite = _open_invite_or_error(token, locale)

    if len(payload.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=t("invite.passwordTooShort", locale, min=MIN_PASSWORD_LENGTH),
        )

    # Invalidate the link first, then create, otherwise two attempts get through.
    if not repo.mark_invite_used(invite["id"]):
        raise HTTPException(status_code=410, detail=t("invite.notValid", locale))

    try:
        sitzungsdaten = provision_account(
            uid=invite["uid"],
            given_name=payload.given_name,
            surname=payload.surname,
            email=invite["email"],
            role=invite["role"],
            custom_role_id=invite["custom_role_id"],
            password=payload.password,
        )
    except Exception as fehler:
        # Whatever half got written, the link has to work again.
        repo.reopen_invite(invite["id"])
        logger.error("invite redeem failed for uid={}: {}", invite["uid"], fehler)
        raise HTTPException(status_code=500, detail=t("invite.createFailed", locale))

    demo_module_zuweisen(sitzungsdaten["user_id"])

    display_name = sitzungsdaten["display_name"]
    store = get_session_store()
    sitzung = store.create(data=sitzungsdaten)
    set_session_cookie(response, sitzung)
    logger.info("invite redeemed for uid={}", invite["uid"])
    return {"status": "ok", "username": invite["uid"], "display_name": display_name}
