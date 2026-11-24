"""Pydantic models for admin endpoints."""

from pydantic import BaseModel, create_model

from src.services.tool_numbers import NUMBERS


class AddWhitelistRequest(BaseModel):
    email: str


class _UpdateSettingsBase(BaseModel):
    """The settings of the system tab, providers and models live in the AI tab."""
    whitelist_enabled: bool | None = None
    # Days a locked test account stays readable before the nightly sweep removes it.
    access_account_delete_after_days: int | None = None
    # Offers the language trainer platform wide, off by default.
    language_training_enabled: bool | None = None
    # Notice banner on the start page, a switch plus free text.
    # Links can be embedded inline in the text as [label](url).
    home_notice_enabled: bool | None = None
    home_notice_text: str | None = None
    # Welcome dialog on an account's very first login, a switch plus free text.
    welcome_modal_enabled: bool | None = None
    welcome_modal_text: str | None = None
    # Contact address, imprint and privacy policy of this installation, the texts in Markdown.
    legal_contact_email: str | None = None
    legal_imprint_de: str | None = None
    legal_imprint_en: str | None = None
    legal_privacy_de: str | None = None
    legal_privacy_en: str | None = None
    # Text recognition when ingesting image-heavy pages, on by default.
    ocr_enabled: bool | None = None
    # Per-workspace source upload cap (admin-tunable, default 30).
    aia_workspace_max_sources: int | None = None
    # Context budget of the chat in characters.
    aia_context_max_chars: int | None = None
    # Context of a specific question, where less is better than more.
    aia_specific_max_chars: int | None = None
    # Context budget of the tools, apart from the chat, and the ceiling of the exercises.
    aia_tool_context_max_chars: int | None = None
    # Language for flashcards, quiz, data table and mind map.
    aia_learning_tools_language: str | None = None
    # Characters per batch for the summary during ingest.
    aia_summary_batch_max_chars: int | None = None
    # Maximum pages per uploaded source.
    aia_source_max_pages: int | None = None
    # Provider and voice for the pronunciation on the flashcard.
    aia_flashcard_voice_provider_id: str | None = None
    aia_flashcard_voice_id: str | None = None
    # Concurrency deliberately no longer lives here, it is measured.
    tts_max_chars_per_request: int | None = None
    # Limits of the global tools, in the count limits -1 means unlimited.
    screencast_max_slides: int | None = None
    transcription_max_minutes: int | None = None
    upload_max_mb: int | None = None
    results_kept_per_user: int | None = None
    tool_max_open_jobs: int | None = None
    # The assessment prompt, an empty text resets it to the default.
    language_diagnosis_prompt: str | None = None
    # The question plan as JSON, an empty text resets it.
    language_diagnosis_question_plan_de: str | None = None
    # Soft ceiling for the answer length of the assessment.
    language_diagnosis_answer_max_chars: int | None = None
    # Adaptive answer behaviour of the chat, empty resets it.
    language_diagnosis_adaptive_behavior: str | None = None
    # Grading rules (LEVEL ASSIGNMENT). Empty string restores the shipped default.
    language_diagnosis_grading_rules: str | None = None
    # Examples per level as JSON, empty resets it.
    language_diagnosis_level_examples: str | None = None
    # Description per level as JSON, empty resets it.
    language_diagnosis_level_descriptions: str | None = None


# The tunable numbers of the tools are not written out one by one: services/tool_numbers.py
# is the one table, and a tool that enters a number there gets its field here for free.
UpdateSettingsRequest = create_model(
    "UpdateSettingsRequest",
    __base__=_UpdateSettingsBase,
    **{n.key: (int | None, None) for n in NUMBERS},
)


class ToggleToolRequest(BaseModel):
    enabled: bool


class MaintenanceToggleRequest(BaseModel):
    enabled: bool


class SetQuotaOverrideRequest(BaseModel):
    limit_value: int  # -1 = unlimited


class VoiceEntry(BaseModel):
    voice_id: str
    name: str
    language: str               # required – e.g. "de", "en"
    description: str | None = None


class CreateProviderRequest(BaseModel):
    name: str
    protocol: str
    base_url: str
    api_key: str | None = None
    voices: list[VoiceEntry] = []
    enabled: bool = True
    initial_capabilities: list[str] | None = None  # if set, skips probe-seeding
    # Requests at once per bucket, checked in the route so the message can be translated.
    concurrency: dict | None = None


class UpdateProviderRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # empty string clears the key
    capabilities: list[str] | None = None  # admin override after probe
    voices: list[VoiceEntry] | None = None
    enabled: bool | None = None
    # Replaces the whole object when present, an empty object clears every cap.
    concurrency: dict | None = None


class DiscoverVoicesRequest(BaseModel):
    base_url: str
    api_key: str | None = None
    voices_path: str | None = None  # default: /v1/audio/voices


class SetFeatureRouteRequest(BaseModel):
    provider_id: int | None = None  # null clears the route
    model_name: str | None = None
    user_choices: list[int] | None = None  # multi-pill provider ids
    provider_models: dict[str, str] | None = None  # per-provider model overrides
    # Temperatur und top_p je Anbieter, leeres Feld heisst nichts mitsenden.
    provider_sampling: dict[str, dict[str, float]] | None = None
    # Second provider for when the first one fails, its model comes from provider_models.
    fallback_provider_id: int | None = None
    # The providers in the admin's order, given it decides first choice and fallback itself.
    provider_order: list[int] | None = None


class SetModelWindowRequest(BaseModel):
    provider_id: int
    model_name: str
    window_tokens: int | None = None  # null goes back to measuring


# ─── Export/Import schema ──────────────────────────────────────────────────

class ExportedProvider(BaseModel):
    name: str
    protocol: str
    base_url: str
    capabilities: list[str] = []
    voices: list[VoiceEntry] = []
    enabled: bool = True
    # Encrypted envelope around the access key, or None.
    api_key: dict | None = None
    # None means an export from before the caps, the existing caps then stay as they are.
    concurrency: dict[str, int] | None = None


class ExportedFeatureRoute(BaseModel):
    feature: str
    provider_name: str | None = None
    model_name: str | None = None
    user_choices: list[str] = []
    provider_models: dict[str, str] = {}
    provider_sampling: dict[str, dict[str, float]] = {}
    fallback_provider_name: str | None = None
    provider_order: list[str] = []


class ExportedConfig(BaseModel):
    schema_version: int
    exported_at: str
    exported_from: str | None = None
    providers: list[ExportedProvider] = []
    feature_routes: list[ExportedFeatureRoute] = []


class ImportConfigRequest(BaseModel):
    config: ExportedConfig


class SetUserDemoRequest(BaseModel):
    is_demo: bool
