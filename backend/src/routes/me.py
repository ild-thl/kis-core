from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src import database as db
from src.dependencies import get_current_user
from src.i18n import get_locale, t
from src.routes._shared import require_user_id
from src.services.consent import GLOBAL_CONSENT_VERSION, has_global_consent

router = APIRouter(prefix="/me", tags=["me"])


class LocaleUpdate(BaseModel):
    locale: str = Field(pattern=r"^(de|en)$")


class LanguageLevelUpdate(BaseModel):
    """The level chosen by hand, one of the six steps."""
    level: Literal["A1", "A2", "B1", "B2", "C1", "C2"]


class TourSeenUpdate(BaseModel):
    """false releases the tour again, then the invitation comes back."""
    seen: bool


class LanguageTrainingUpdate(BaseModel):
    """The one switch, yes on the start question or the toggle in the profile."""
    active: bool


def _language_training_state(user_id: int) -> dict:
    """The three fields the level page and the start question read."""
    state = db.get_user_language_training(user_id)
    asked = state["language_training_asked_at"]
    return {
        # Admin switch and permission together, that is what the page asks about.
        "language_training_enabled": db.is_language_training_offered(user_id),
        "language_training_active": state["language_training_active"],
        "language_training_asked_at": asked.isoformat() if asked else None,
    }


def _language_level_state(user_id: int) -> dict:
    """The level with date and origin, as the profile shows it."""
    ll = db.get_user_language_level(user_id)
    set_at = ll["language_level_set_at"]
    return {
        "language_level": ll["language_level"],
        "language_level_set_at": set_at.isoformat() if set_at else None,
        "language_level_source": ll.get("language_level_source"),
    }


@router.get("")
def get_me(
    user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    user_id = require_user_id(user, locale)
    row = db.get_user_by_id(user_id)
    if not row:
        raise HTTPException(status_code=404, detail=t("user.notFound", locale))
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "email": row["email"],
        "role": row["role"],
        "locale": row.get("locale", "de"),
        "tour_seen_at": row["tour_seen_at"].isoformat() if row.get("tour_seen_at") else None,
        "global_consent_accepted": has_global_consent(user_id),
        "global_consent_at": row["global_consent_at"].isoformat() if row.get("global_consent_at") else None,
        **_language_level_state(user_id),
        **_language_training_state(user_id),
    }


@router.post("/consent")
def accept_global_consent(
    user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    """The one notice every account accepts once, before any service becomes reachable."""
    user_id = require_user_id(user, locale)
    db.set_global_consent(user_id, GLOBAL_CONSENT_VERSION)
    return {"ok": True}


@router.post("/tour-seen")
def update_tour_seen(
    payload: TourSeenUpdate,
    user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    """Remembers per account whether the tour was done, so it survives a browser change."""
    user_id = require_user_id(user, locale)
    db.set_user_tour_seen(user_id, payload.seen)
    return {"seen": payload.seen}


@router.patch("/language-training")
def update_language_training(
    payload: LanguageTrainingUpdate,
    user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    """Answers the start question on the home page, admin switch and permission gate it."""
    user_id = require_user_id(user, locale)
    if not db.is_language_training_offered(user_id):
        raise HTTPException(status_code=403, detail=t("ai.languageTraining.disabled", locale))
    db.set_user_language_training(user_id, payload.active)
    return _language_training_state(user_id)


@router.put("/language-level")
def update_language_level(
    payload: LanguageLevelUpdate,
    user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    """Sets the level by hand, the same two switches gate it as the test."""
    user_id = require_user_id(user, locale)
    if not db.is_language_training_offered(user_id):
        raise HTTPException(status_code=403, detail=t("ai.languageTraining.off", locale))
    db.set_user_language_level(user_id, payload.level, "self")
    return _language_level_state(user_id)


@router.patch("/locale")
def update_locale(
    payload: LocaleUpdate,
    user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    user_id = require_user_id(user, locale)
    db.update_user_locale(user_id, payload.locale)
    return {"locale": payload.locale}
