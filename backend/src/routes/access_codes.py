"""The public side of the access codes, the code is the credential."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from loguru import logger
from pydantic import BaseModel, Field

from src import database
from src.dependencies import get_session_store
from src.features.access_codes import repository as repo
from src.features.access_codes.service import new_username, normalize_code, status_of
from src.features.accounts.demo_onboarding import demo_module_zuweisen
from src.features.accounts.provisioning import provision_account
from src.features.accounts.uid import unique_uid
from src.i18n import get_locale, t
from src.features.accounts.passwords import generate_password
from src.features.accounts.login import authenticate
from src.routes._shared import set_session_cookie

router = APIRouter(prefix="/access-codes", tags=["access codes"])


def _live_code(code: str, locale: str, *, seat_needed: bool) -> dict:
    """Fetches the code and lets only a usable one through."""
    eintrag = repo.get_code_by_code(normalize_code(code))
    if eintrag is None:
        raise HTTPException(status_code=404, detail=t("access.codeUnknown", locale))

    zustand = status_of(
        active=eintrag["active"],
        used_count=eintrag["used_count"],
        max_uses=eintrag["max_uses"],
        valid_until=eintrag["valid_until"],
        now=datetime.now(),
    )
    # Renewing takes no seat, so a full code still renews.
    tot = zustand != "active" if seat_needed else zustand in ("disabled", "expired")
    if tot:
        raise HTTPException(status_code=410, detail=t("access.codeNotValid", locale))
    return eintrag


def _enroll_into_code_workspaces(code_id: int, user_id: int) -> None:
    """Puts the account into the workspaces the admin tied to the code, never blocks the way in."""
    try:
        repo.enroll_into_code_workspaces(code_id, [user_id])
    except Exception as fehler:
        logger.error("access code {} could not enroll user_id={}: {}", code_id, user_id, fehler)


def _set_session(response: Response, daten: dict) -> None:
    """Puts the session into a cookie, same shape as the login."""
    set_session_cookie(response, get_session_store().create(data=daten))


class RedeemPayload(BaseModel):
    code: str = Field(..., min_length=3, max_length=32)


@router.post("/redeem")
def redeem(payload: RedeemPayload, response: Response, locale: str = Depends(get_locale)):
    eintrag = _live_code(payload.code, locale, seat_needed=True)

    # A deleted custom role would blow up halfway through, so the code counts as dead.
    if eintrag["role"] == "custom" and database.get_custom_role(eintrag["custom_role_id"]) is None:
        logger.error("access code {} points at a missing custom role", eintrag["id"])
        raise HTTPException(status_code=410, detail=t("access.codeNotValid", locale))

    uid = unique_uid(new_username(), lambda name: database.get_user_by_username(name) is not None)
    password = generate_password()

    # Take the seat first, then create, otherwise the limit leaks under load.
    if not repo.claim_use(eintrag["id"]):
        raise HTTPException(status_code=410, detail=t("access.codeNotValid", locale))

    try:
        sitzungsdaten = provision_account(
            uid=uid,
            given_name="",
            surname="",
            email=None,
            role=eintrag["role"],
            custom_role_id=eintrag["custom_role_id"],
            password=password,
        )
    except Exception as fehler:
        repo.release_use(eintrag["id"])
        logger.error("access code redeem failed for uid={}: {}", uid, fehler)
        raise HTTPException(status_code=500, detail=t("access.createFailed", locale))

    stunden = eintrag["access_hours"]
    frist = datetime.now() + timedelta(hours=stunden) if stunden else None
    try:
        repo.set_user_access(sitzungsdaten["user_id"], expires_at=frist, code_id=eintrag["id"])
    except Exception as fehler:
        # The account exists but never got its deadline, so it must not stay usable.
        logger.error("access deadline write failed for uid={}: {}", uid, fehler)
        database.update_user(
            sitzungsdaten["user_id"],
            sitzungsdaten["display_name"],
            sitzungsdaten["email"],
            0,
        )
        # The whitelist has to go too, otherwise the next login switches the account back on.
        if sitzungsdaten["email"]:
            database.remove_from_whitelist(sitzungsdaten["email"])
        raise HTTPException(status_code=500, detail=t("access.createFailed", locale))
    sitzungsdaten["access_expires_at"] = frist.isoformat() if frist else None

    # Testers get a working example right away, without a demo module this is simply a no-op.
    demo_module_zuweisen(sitzungsdaten["user_id"])
    _enroll_into_code_workspaces(eintrag["id"], sitzungsdaten["user_id"])

    _set_session(response, sitzungsdaten)

    logger.info("access code redeemed for uid={} until={}", uid, frist.isoformat() if frist else "never")
    return {
        "status": "ok",
        "username": uid,
        "password": password,
        "expires_at": frist,
        # Lets the redeem page skip straight into the app for event codes with the switch off.
        "show_credentials": eintrag["show_credentials"],
    }


class RenewPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
    code: str = Field(..., min_length=3, max_length=32)


@router.post("/renew")
def renew(payload: RenewPayload, response: Response, locale: str = Depends(get_locale)):

    konto = authenticate(payload.username.strip(), payload.password)
    if konto is None:
        raise HTTPException(status_code=401, detail=t("access.invalidCredentials", locale))

    if konto["access_expires_at"] is None:
        raise HTTPException(status_code=403, detail=t("access.notATestAccount", locale))
    # A missing key means the row predates the active column and counts as active.
    if not konto.get("active", 1):
        raise HTTPException(status_code=403, detail="account_not_activated")

    eintrag = _live_code(payload.code, locale, seat_needed=False)
    stunden = eintrag["access_hours"]
    frist = datetime.now() + timedelta(hours=stunden) if stunden else None
    repo.set_user_access(konto["id"], expires_at=frist, code_id=eintrag["id"])
    _enroll_into_code_workspaces(eintrag["id"], konto["id"])

    name = konto["username"]
    _set_session(response, {
        "user_id": konto["id"],
        "username": name,
        "display_name": konto["display_name"] or name,
        "email": konto["email"] or "",
        "role": konto["role"] or "user",
        "custom_role_id": konto["custom_role_id"],
        "access_expires_at": frist.isoformat() if frist else None,
    })

    logger.info("access renewed for uid={} until={}", name, frist.isoformat() if frist else "never")
    return {"status": "ok", "username": name, "expires_at": frist}
