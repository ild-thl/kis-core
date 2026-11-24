"""The public page of a reset link, the key in the link is the credential."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from src import database
from src.dependencies import get_session_store, get_settings
from src.features.accounts.passwords import PasswordTooLongError, hash_password
from src.features.password_reset import repository as repo
from src.features.password_reset.service import can_get_reset_link, hash_token, status_of
from src.i18n import get_locale, t
from src.routes._shared import MIN_PASSWORD_LENGTH

router = APIRouter(prefix="/password-reset", tags=["password reset"])


def _open_token_or_error(token: str, locale: str) -> tuple[dict, dict]:
    """Fetches link and account and lets only an open link of a still eligible account through."""
    eintrag = repo.get_by_hash(hash_token(token))
    if eintrag is None:
        raise HTTPException(status_code=404, detail=t("passwordReset.notFound", locale))

    zustand = status_of(
        used_at=eintrag["used_at"], expires_at=eintrag["expires_at"], now=datetime.now()
    )
    konto = database.get_user_by_id(eintrag["user_id"])
    if zustand != "open" or not konto or not can_get_reset_link(dict(konto), get_settings().admin_email):
        raise HTTPException(status_code=410, detail=t("passwordReset.notValid", locale))
    return eintrag, dict(konto)


@router.get("/{token}")
def read_reset_link(token: str, locale: str = Depends(get_locale)):
    _, konto = _open_token_or_error(token, locale)
    return {"uid": konto["username"]}


class ResetPayload(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)


@router.post("/{token}")
def reset_password(token: str, payload: ResetPayload, locale: str = Depends(get_locale)):
    eintrag, konto = _open_token_or_error(token, locale)

    if len(payload.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=t("passwordReset.tooShort", locale, min=MIN_PASSWORD_LENGTH),
        )
    try:
        neuer_hash = hash_password(payload.password)
    except PasswordTooLongError:
        raise HTTPException(status_code=400, detail=t("passwordReset.tooLong", locale))

    # Close the link first, otherwise two attempts get through.
    if not repo.mark_used(eintrag["id"]):
        raise HTTPException(status_code=410, detail=t("passwordReset.notValid", locale))

    try:
        database.set_user_password(konto["id"], neuer_hash)
    except Exception as fehler:
        repo.reopen(eintrag["id"])
        logger.error("password reset failed for user_id={}: {}", konto["id"], fehler)
        raise HTTPException(status_code=500, detail=t("passwordReset.failed", locale))

    # Whoever is still logged in with the old password has to log in again.
    get_session_store().destroy_for_users([konto["id"]])
    logger.info("password reset via link for user_id={}", konto["id"])
    return {"status": "ok", "username": konto["username"]}
