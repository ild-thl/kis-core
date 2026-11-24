"""Reads and writes the system-wide settings, providers live in the AI tab."""

import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException

from src import database as db
from src.dependencies_rbac import permissions_of, require_any_settings
from src.features.campus.services import settings as campus_settings
from src.routes.health import DEFAULT_WELCOME_MODAL_TEXT, LEGAL_KEYS
from src.i18n import (
    DEFAULT_LEARNING_TOOLS_LANGUAGE,
    TRANSCRIPT_LANGUAGES,
    get_locale,
    t,
)
from src.permissions_registry import SETTING_FIELD_PERMISSIONS
from src.limits import (
    ACCESS_ACCOUNT_DELETE_AFTER_DAYS,
    TTS_MAX_CHARS_PER_REQUEST,
    AIA_CONTEXT_MAX_CHARS,
    AIA_CONTEXT_HARD_CAP,
    AIA_SPECIFIC_MAX_CHARS,
    AIA_TOOL_CONTEXT_MAX_CHARS,
    AIA_TOOL_CONTEXT_HARD_CAP,
    AIA_SUMMARY_BATCH_MAX_CHARS,
    AIA_SOURCE_MAX_PAGES,
    AIA_WORKSPACE_MAX_SOURCES,
    AIA_WORKSPACE_MAX_SOURCES_CAP,
)
from src.routes.admin._models import UpdateSettingsRequest
from src.services import tool_limits, tool_numbers
from src.services.aia_diagnosis_chat import (
    ADAPTIVE_BEHAVIOR_SETTING,
    ANSWER_MAX_CHARS_SETTING,
    DEFAULT_ANSWER_MAX_CHARS,
    DEFAULT_DIAGNOSIS_PROMPT,
    DEFAULT_GERMAN_QUESTION_PLAN,
    DEFAULT_GRADING_RULES,
    DEFAULT_LEVEL_EXAMPLES,
    _LEGACY_GRADING_RULES,
    EXAMPLE_LEVELS,
    GRADING_RULES_SETTING,
    LEVEL_EXAMPLES_SETTING,
    MAX_MESSAGE_CHARS,
    MAX_PROMPT_CHARS,
    MIN_FREE_TEXT_QUESTIONS,
    QUESTION_PLAN_SETTING,
    first_incomplete_question,
    question_plan_has_enough_free_text,
    question_plan_is_valid,
)
from src.services.aia_adaptive_chat import (
    DEFAULT_ADAPTIVE_BEHAVIOR,
    _LEGACY_ADAPTIVE_BEHAVIOR,
)
from src.services.aia_level_ladder import (
    DEFAULT_LEVEL_DESCRIPTIONS,
    LEVEL_DESCRIPTIONS_SETTING,
    LEVELS,
    resolve_prompt_setting,
)

router = APIRouter(tags=["admin: settings"])

# Ten years, anything beyond that is a typo rather than a retention rule.
MAX_DELETE_AFTER_DAYS = 3650
# Both notices of the start page share this length.
MAX_NOTICE_CHARS = 1000
MAX_LEGAL_CHARS = 50_000
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
logger = logging.getLogger(__name__)
# Below this a context budget holds no usable excerpt.
MIN_CONTEXT_CHARS = 1000


def _permission_for(field_name: str) -> str | None:
    """The right a settings field hangs off, from the catalogue or from the number table."""
    return SETTING_FIELD_PERMISSIONS.get(field_name) or tool_numbers.permission_for(field_name)


def _assert_fields_allowed(body: UpdateSettingsRequest, perms, locale: str) -> None:
    """Checks every submitted field against the right of its page."""
    for field_name, value in body.model_dump().items():
        if value is None:
            continue
        needed = _permission_for(field_name)
        if needed is None or needed not in perms.keys:
            raise HTTPException(
                status_code=403,
                detail=t("auth.settingFieldForbidden", locale, field=field_name),
            )


@router.get("/settings")
def get_settings(_admin=Depends(require_any_settings)):
    def _enabled(key: str, default: str = "true") -> bool:
        return db.get_setting(key, default).lower() == "true"

    campus_map = campus_settings.read()
    return {
        "whitelist_enabled": _enabled("whitelist_enabled"),
        # Days a locked test account stays readable, 0 switches the sweep off.
        "access_account_delete_after_days": int(
            db.get_setting("access_account_delete_after_days", str(ACCESS_ACCOUNT_DELETE_AFTER_DAYS))
            or ACCESS_ACCOUNT_DELETE_AFTER_DAYS
        ),
        # The language trainer platform wide, without it no course can turn it on.
        "language_training_enabled": _enabled("language_training_enabled", "false"),
        # Home page notice banner, shown to all users above the next appointments.
        "home_notice_enabled": _enabled("home_notice_enabled", "false"),
        "home_notice_text": db.get_setting("home_notice_text", ""),
        # First-login welcome dialog, on by default so onboarding is never blank.
        "welcome_modal_enabled": _enabled("welcome_modal_enabled"),
        "welcome_modal_text": db.get_setting("welcome_modal_text", DEFAULT_WELCOME_MODAL_TEXT),
        **{key: db.get_setting(key, "") for key in LEGAL_KEYS},
        # Campus map outside KIS, an empty address means no map anywhere.
        "campus_map_url": campus_map.map_url,
        "campus_map_enabled": campus_map.map_enabled,
        # OCR on image-heavy pages during indexing (system-wide, default on)
        "ocr_enabled": _enabled("ocr_enabled"),
        # Workspace limits (admin-tunable)
        "aia_workspace_max_sources": int(
            db.get_setting("aia_workspace_max_sources", str(AIA_WORKSPACE_MAX_SOURCES))
        ),
        # KI-tutor chat context budget (chars). Default sized for 32k models.
        "aia_context_max_chars": int(
            db.get_setting("aia_context_max_chars", str(AIA_CONTEXT_MAX_CHARS))
        ),
        # Context of a specific question, apart from the overview budget above.
        "aia_specific_max_chars": int(
            db.get_setting("aia_specific_max_chars", str(AIA_SPECIFIC_MAX_CHARS))
        ),
        # Context budget of the tools, apart from the chat. The exercise tools take
        # only what their number of exercises needs, this is their ceiling.
        "aia_tool_context_max_chars": int(
            db.get_setting("aia_tool_context_max_chars", str(AIA_TOOL_CONTEXT_MAX_CHARS))
        ),
        # Language of the four learning tools, the language trainer stays German.
        "aia_learning_tools_language": db.get_setting(
            "aia_learning_tools_language", DEFAULT_LEARNING_TOOLS_LANGUAGE
        ),
        # Ingest-side DOC SUMMARY per-batch char cap (bigger = fewer summary calls).
        "aia_summary_batch_max_chars": int(
            db.get_setting("aia_summary_batch_max_chars", str(AIA_SUMMARY_BATCH_MAX_CHARS))
        ),
        # Max pages per uploaded source (long scripts → upload chapter-wise).
        "aia_source_max_pages": int(
            db.get_setting("aia_source_max_pages", str(AIA_SOURCE_MAX_PAGES))
        ),
        # Tunable numbers of the tools, shown as they actually apply, plus their ranges
        # so the admin area never has to repeat a limit that is defined here.
        **{n.key: tool_numbers.value_of(n.key) for n in tool_numbers.NUMBERS},
        "tool_numbers": [
            {"key": n.key, "tool": n.tool, "default": n.default,
             "min": n.smallest, "max": n.largest}
            for n in tool_numbers.NUMBERS
        ],
        # Pronunciation on the flashcard, empty means not set up yet.
        "aia_flashcard_voice_provider_id": db.get_setting("aia_flashcard_voice_provider_id", ""),
        "aia_flashcard_voice_id": db.get_setting("aia_flashcard_voice_id", ""),
        # Characters per speech request, stays configurable because it is a provider trait.
        "tts_max_chars_per_request": int(
            db.get_setting("tts_max_chars_per_request", str(TTS_MAX_CHARS_PER_REQUEST))
        ),
        # Limits of the global tools, in minutes and MB as on the card.
        "screencast_max_slides": tool_limits.max_screencast_slides(),
        "transcription_max_minutes": tool_limits.max_transcription_seconds() // 60,
        "upload_max_mb": tool_limits.max_upload_bytes() // (1024 * 1024),
        "results_kept_per_user": tool_limits.results_kept_per_user(),
        "tool_max_open_jobs": tool_limits.max_open_jobs(),
        # The assessment prompt, a placeholder carries the language.
        "language_diagnosis_prompt": db.get_setting(
            "language_diagnosis_prompt", DEFAULT_DIAGNOSIS_PROMPT
        ),
        "language_diagnosis_prompt_default": DEFAULT_DIAGNOSIS_PROMPT,
        # The question plan, empty means the default is active.
        "language_diagnosis_question_plan_de": db.get_setting(QUESTION_PLAN_SETTING, ""),
        # The German tab fills it and resets to the shipped German set.
        "language_diagnosis_question_plan_default": DEFAULT_GERMAN_QUESTION_PLAN,
        "language_diagnosis_answer_max_chars": int(
            db.get_setting(ANSWER_MAX_CHARS_SETTING, str(DEFAULT_ANSWER_MAX_CHARS))
        ),
        # A stored old default counts as not set.
        "language_diagnosis_adaptive_behavior": resolve_prompt_setting(
            db.get_setting(ADAPTIVE_BEHAVIOR_SETTING, ""),
            _LEGACY_ADAPTIVE_BEHAVIOR,
            DEFAULT_ADAPTIVE_BEHAVIOR,
        ),
        "language_diagnosis_adaptive_behavior_default": DEFAULT_ADAPTIVE_BEHAVIOR,
        # Grading method plus the level ladder with description and examples.
        "language_diagnosis_grading_rules": resolve_prompt_setting(
            db.get_setting(GRADING_RULES_SETTING, ""),
            _LEGACY_GRADING_RULES,
            DEFAULT_GRADING_RULES,
        ),
        "language_diagnosis_grading_rules_default": DEFAULT_GRADING_RULES,
        "language_diagnosis_level_examples": db.get_setting(LEVEL_EXAMPLES_SETTING, ""),
        "language_diagnosis_level_examples_default": DEFAULT_LEVEL_EXAMPLES,
        "language_diagnosis_example_levels": EXAMPLE_LEVELS,
        "language_diagnosis_level_descriptions": db.get_setting(
            LEVEL_DESCRIPTIONS_SETTING, ""
        ),
        "language_diagnosis_level_descriptions_default": DEFAULT_LEVEL_DESCRIPTIONS,
    }


def _save_flag(key: str, value: bool | None) -> None:
    if value is not None:
        db.set_setting(key, "true" if value else "false")


def _save_number(key: str, value: int | None, lo: int, hi: int, message: str, locale: str) -> None:
    """Stores a number inside its range, the range is there against typos."""
    if value is None:
        return
    if value < lo or value > hi:
        raise HTTPException(status_code=400, detail=t(message, locale, min=lo, max=hi))
    db.set_setting(key, str(value))


def _save_text(key: str, value: str | None, max_chars: int, message: str, locale: str,
               default: str = "") -> None:
    """Stores a trimmed text up to its length, an empty one saves the default."""
    if value is None:
        return
    stripped = value.strip()
    if len(stripped) > max_chars:
        raise HTTPException(status_code=400, detail=t(message, locale, max=max_chars))
    db.set_setting(key, stripped or default)


def _save_level_texts(key: str, value: str | None, levels, locale: str) -> None:
    """One text per level as JSON, empty resets, otherwise every key must be a known level."""
    if value is None:
        return
    stripped = value.strip()
    if stripped:
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = None
        valid = (
            isinstance(data, dict)
            and bool(data)
            and all(k in levels and isinstance(v, str) for k, v in data.items())
        )
        if not valid:
            raise HTTPException(
                status_code=400,
                detail=t("admin.settings.diagnosisExamplesInvalid", locale),
            )
    db.set_setting(key, stripped)


def _save_question_plan(value: str | None, locale: str) -> None:
    """An empty plan resets it, a filled one must be valid."""
    if value is None:
        return
    stripped = value.strip()
    if stripped:
        if not question_plan_is_valid(stripped):
            raise HTTPException(
                status_code=400,
                detail=t("admin.settings.diagnosisPlanInvalid", locale),
            )
        if (incomplete := first_incomplete_question(stripped)) is not None:
            # Half a line can no longer be saved, the message names the line number.
            raise HTTPException(
                status_code=400,
                detail=t("admin.settings.diagnosisPlanIncomplete", locale,
                         number=incomplete),
            )
        if not question_plan_has_enough_free_text(stripped):
            # A plan without enough free text would rest the level on nothing written.
            raise HTTPException(
                status_code=400,
                detail=t("admin.settings.diagnosisPlanTooFewFreeText", locale,
                         min=MIN_FREE_TEXT_QUESTIONS),
            )
    db.set_setting(QUESTION_PLAN_SETTING, stripped)


def _save_general(body: UpdateSettingsRequest, locale: str) -> None:
    """Access, the language trainer switch, the two notices of the start page and OCR."""
    _save_flag("whitelist_enabled", body.whitelist_enabled)
    # Grace period before an expired test account is deleted.
    _save_number("access_account_delete_after_days", body.access_account_delete_after_days,
                 0, MAX_DELETE_AFTER_DAYS, "admin.settings.deleteAfterDaysOutOfRange", locale)
    # The language trainer off hides it everywhere, the per-course choice stays.
    _save_flag("language_training_enabled", body.language_training_enabled)
    # The notice banner switch is independent of the text, the text is length limited.
    _save_flag("home_notice_enabled", body.home_notice_enabled)
    _save_text("home_notice_text", body.home_notice_text, MAX_NOTICE_CHARS,
               "admin.settings.homeNoticeTooLong", locale)
    _save_flag("welcome_modal_enabled", body.welcome_modal_enabled)
    _save_text("welcome_modal_text", body.welcome_modal_text, MAX_NOTICE_CHARS,
               "admin.settings.welcomeModalTooLong", locale)
    _save_flag("ocr_enabled", body.ocr_enabled)
    _save_legal(body, locale)
    _save_campus_map(body, locale)


def _save_legal(body: UpdateSettingsRequest, locale: str) -> None:
    """Contact address and the legal texts, the address must look like one or stay empty."""
    email = body.legal_contact_email
    if email is not None:
        email = email.strip()
        if email and (len(email) > 254 or not _EMAIL.match(email)):
            raise HTTPException(status_code=400, detail=t("admin.settings.contactEmailInvalid", locale))
        db.set_setting("legal_contact_email", email)
    for key in LEGAL_KEYS[1:]:
        _save_text(key, getattr(body, key), MAX_LEGAL_CHARS, "admin.settings.legalTextTooLong", locale)


def _save_campus_map(body: UpdateSettingsRequest, locale: str) -> None:
    """The map address must be a web address or empty, the switch hides the map without losing it."""
    values = {}
    if body.campus_map_url is not None:
        url = body.campus_map_url.strip()
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail=t("campus.urlInvalid", locale))
        values["map_url"] = url
    if body.campus_map_enabled is not None:
        values["map_enabled"] = body.campus_map_enabled
    if values:
        campus_settings.write(values)


def _save_language_diagnosis(body: UpdateSettingsRequest, locale: str) -> None:
    """The assessment: its prompts, the question plan and the level ladder."""
    too_long = "admin.settings.diagnosisPromptTooLong"
    # An empty prompt saves the default, the assessment is never without instructions.
    _save_text("language_diagnosis_prompt", body.language_diagnosis_prompt, MAX_PROMPT_CHARS,
               too_long, locale, DEFAULT_DIAGNOSIS_PROMPT)
    _save_question_plan(body.language_diagnosis_question_plan_de, locale)
    # Soft answer length, it only steers the display.
    _save_number(ANSWER_MAX_CHARS_SETTING, body.language_diagnosis_answer_max_chars,
                 1, MAX_MESSAGE_CHARS, "admin.settings.answerMaxCharsOutOfRange", locale)
    _save_text(ADAPTIVE_BEHAVIOR_SETTING, body.language_diagnosis_adaptive_behavior, MAX_PROMPT_CHARS,
               too_long, locale, DEFAULT_ADAPTIVE_BEHAVIOR)
    _save_text(GRADING_RULES_SETTING, body.language_diagnosis_grading_rules, MAX_PROMPT_CHARS,
               too_long, locale, DEFAULT_GRADING_RULES)
    _save_level_texts(LEVEL_EXAMPLES_SETTING, body.language_diagnosis_level_examples, EXAMPLE_LEVELS, locale)
    _save_level_texts(LEVEL_DESCRIPTIONS_SETTING, body.language_diagnosis_level_descriptions, LEVELS, locale)


def _save_assistant_limits(body: UpdateSettingsRequest, locale: str) -> None:
    """Sources, context budgets and the tunable numbers of the learning assistant."""
    _save_number("aia_workspace_max_sources", body.aia_workspace_max_sources,
                 1, AIA_WORKSPACE_MAX_SOURCES_CAP, "admin.settings.maxSourcesOutOfRange", locale)
    # Context budget of the chat, the specific question shares its limits.
    _save_number("aia_context_max_chars", body.aia_context_max_chars,
                 MIN_CONTEXT_CHARS, AIA_CONTEXT_HARD_CAP, "admin.settings.contextBudgetOutOfRange", locale)
    _save_number("aia_specific_max_chars", body.aia_specific_max_chars,
                 MIN_CONTEXT_CHARS, AIA_CONTEXT_HARD_CAP, "admin.settings.contextBudgetOutOfRange", locale)
    # Context budget of the tools, with its own higher ceiling than the chat's.
    _save_number("aia_tool_context_max_chars", body.aia_tool_context_max_chars,
                 MIN_CONTEXT_CHARS, AIA_TOOL_CONTEXT_HARD_CAP, "admin.settings.toolContextBudgetOutOfRange", locale)

    # Each tunable number against its own range, so no tool ever has to repair one it reads back.
    for zahl in tool_numbers.NUMBERS:
        wert = getattr(body, zahl.key, None)
        if wert is None:
            continue
        if wert < zahl.smallest or wert > zahl.largest:
            raise HTTPException(
                status_code=400,
                detail=t("admin.settings.numberOutOfRange", locale, field=zahl.key,
                         min=zahl.smallest, max=zahl.largest),
            )
        db.set_setting(zahl.key, str(wert))

    # Only a code from the one list, otherwise it would end up verbatim in the job.
    if body.aia_learning_tools_language is not None:
        value = (body.aia_learning_tools_language or "").strip().lower()
        if value not in TRANSCRIPT_LANGUAGES:
            raise HTTPException(
                status_code=400,
                detail=t("admin.settings.learningToolsLanguageUnknown", locale),
            )
        db.set_setting("aia_learning_tools_language", value)

    _save_number("aia_summary_batch_max_chars", body.aia_summary_batch_max_chars,
                 10_000, 500_000, "admin.settings.summaryBatchOutOfRange", locale)
    _save_number("aia_source_max_pages", body.aia_source_max_pages,
                 1, 2000, "admin.settings.maxPagesOutOfRange", locale)


def _save_tool_limits(body: UpdateSettingsRequest, locale: str) -> None:
    """Limits of the global tools and the voice settings."""
    # Only the two count limits know -1 for unlimited.
    for feld, schluessel, unten, oben, darf_unbegrenzt in (
        (body.screencast_max_slides, "screencast_max_slides", 1, 200, False),
        (body.transcription_max_minutes, "transcription_max_minutes", 5, 480, False),
        (body.upload_max_mb, "upload_max_mb", 10, 2000, False),
        (body.results_kept_per_user, "results_kept_per_user", 1, 10000, True),
        (body.tool_max_open_jobs, "tool_max_open_jobs", 1, 100, True),
    ):
        if feld is None:
            continue
        if not (unten <= feld <= oben) and not (darf_unbegrenzt and feld == -1):
            raise HTTPException(
                status_code=400,
                detail=t("admin.settings.toolLimitOutOfRange", locale, min=unten, max=oben),
            )
        db.set_setting(schluessel, str(feld))

    # Empty is valid and turns the speaker off.
    if body.aia_flashcard_voice_provider_id is not None:
        raw = body.aia_flashcard_voice_provider_id.strip()
        if raw and not raw.isdigit():
            raise HTTPException(
                status_code=400,
                detail=t("admin.settings.flashcardVoiceProviderInvalid", locale),
            )
        db.set_setting("aia_flashcard_voice_provider_id", raw)

    if body.aia_flashcard_voice_id is not None:
        db.set_setting("aia_flashcard_voice_id", body.aia_flashcard_voice_id.strip())

    # Too large runs into the timeout, too small fragments the recording.
    _save_number("tts_max_chars_per_request", body.tts_max_chars_per_request,
                 50, 10_000, "admin.settings.ttsMaxCharsOutOfRange", locale)


@router.patch("/settings")
def update_settings(
    body: UpdateSettingsRequest,
    admin=Depends(require_any_settings),
    locale: str = Depends(get_locale),
):
    """Saves the submitted fields in a fixed order, the first invalid one stops the rest."""
    _assert_fields_allowed(body, permissions_of(admin), locale)
    _save_general(body, locale)
    _save_language_diagnosis(body, locale)
    _save_assistant_limits(body, locale)
    _save_tool_limits(body, locale)
    # Legal texts keep a trace of who changed them and when.
    legal = [key for key in LEGAL_KEYS if getattr(body, key) is not None]
    if legal:
        logger.info("legal settings changed by %s: %s", admin.get("username"), ", ".join(legal))
    return {"ok": True}
