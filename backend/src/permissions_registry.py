# backend/src/permissions_registry.py
"""The catalogue of all permissions, the texts live in the frontend language files."""

from src.modules import MODULE_AIA, MODULE_TOOLS
from src.tools_registry import ALL_TOOL_KEYS

# Two chapters: what someone uses themselves and what they manage for others.
CHAPTER_USE = "benutzen"
CHAPTER_MANAGE = "verwalten"

# The groups are named like the areas of the sidebar.
GROUP_AIA = "aia"
GROUP_TOOLS = "tools"
GROUP_SET_TOOLS = "set.werkzeuge"
GROUP_SET_AIA = "set.assistent"
GROUP_SET_STATS = "set.statistik"
GROUP_SET_PROVIDERS = "set.anbieter"
GROUP_SET_USERS = "set.nutzer"
GROUP_SET_SYSTEM = "set.system"
GROUP_SET_MASCOT = "set.mascot"
GROUP_SET_EVENT = "set.event"
GROUP_SET_CAMPUS = "set.campus"
GROUP_GENERAL = "general"

# === Allgemein ================================================================
PERM_GENERAL_WELCOME = "general.welcome"
PERM_GENERAL_MANUAL = "general.manual"
# Connecting one's own account at an outside voice service, at one's own responsibility.
PERM_GENERAL_INTERFACES = "general.interfaces"

GENERAL_KEYS: tuple[str, ...] = (PERM_GENERAL_WELCOME, PERM_GENERAL_MANUAL, PERM_GENERAL_INTERFACES)

# === KI-Assistent ============================================================
PERM_AIA_USE = "aia.use"
PERM_AIA_WORKSPACE_CREATE = "aia.workspace.create"
# The person's own language level and test.
PERM_AIA_LANGUAGE_LEVEL = "aia.language_level"

AIA_KEYS: tuple[str, ...] = (
    PERM_AIA_USE,
    PERM_AIA_WORKSPACE_CREATE,
    PERM_AIA_LANGUAGE_LEVEL,
)

# Derived from the tool list so a new tool is registered only once.
TOOL_PERM_PREFIX = "tools."
TOOL_KEYS: tuple[str, ...] = tuple(f"{TOOL_PERM_PREFIX}{k}" for k in ALL_TOOL_KEYS)


def tool_key_of(permission: str) -> str:
    """``tools.translation`` -> ``translation``."""
    return permission[len(TOOL_PERM_PREFIX):]


# One key per page of the area.
SETTINGS_PREFIX = "settings."

PERM_SET_TOOLS_RELEASE = "settings.werkzeuge.release"
PERM_SET_TOOLS_JOBS = "settings.werkzeuge.jobs"
PERM_SET_TOOLS_STATS = "settings.werkzeuge.stats"
PERM_SET_TOOLS_LIMITS = "settings.werkzeuge.limits"
PERM_SET_AIA_SOURCES = "settings.assistent.sources"
PERM_SET_AIA_LEVEL = "settings.assistent.level"
PERM_SET_AIA_USAGE = "settings.assistent.usage"
PERM_SET_PROVIDERS = "settings.anbieter"
PERM_SET_USERS_PENDING = "settings.nutzer.pending"
PERM_SET_USERS_WHITELIST = "settings.nutzer.whitelist"
PERM_SET_USERS_ALL = "settings.nutzer.users"
PERM_SET_USERS_ROLES = "settings.nutzer.roles"
# Log in as someone else to see a reported problem oneself.
PERM_SET_USERS_IMPERSONATE = "settings.nutzer.impersonate"
PERM_SET_USERS_FEEDBACK = "settings.nutzer.feedback"
PERM_SET_USERS_EVALUATION = "settings.nutzer.evaluation"
# Label and hint now hang off PERM_SET_SYSTEM.
PERM_SET_SYSTEM = "settings.system"
PERM_SET_MASCOT = "settings.mascot"
# The stands and the event block of the start page, including the stand codes.
PERM_SET_EVENT = "settings.event"
# Crawl, map link and retention of the campus assistant.
PERM_SET_CAMPUS = "settings.campus"
# Two statistics tabs keep their old key so roles lose nothing.
PERM_SET_STATS_USERS = "settings.statistik.nutzer"
PERM_SET_STATS_MODELS = "settings.statistik.modelle"
# Not a settings right but the right to keep working during maintenance.
PERM_MAINTENANCE_ACCESS = "settings.wartung.zugang"

# One group per area of the sidebar.
SET_TOOLS_KEYS: tuple[str, ...] = (
    PERM_SET_TOOLS_RELEASE,
    PERM_SET_TOOLS_JOBS,
    PERM_SET_TOOLS_LIMITS,
)
SET_AIA_KEYS: tuple[str, ...] = (PERM_SET_AIA_SOURCES, PERM_SET_AIA_LEVEL)
# Own modules are read at the module itself, so only the platform-wide numbers are a right.
SET_STATS_KEYS: tuple[str, ...] = (
    PERM_SET_AIA_USAGE,
    PERM_SET_STATS_USERS,
    PERM_SET_TOOLS_STATS,
    PERM_SET_STATS_MODELS,
)
SET_PROVIDER_KEYS: tuple[str, ...] = (PERM_SET_PROVIDERS,)
SET_USER_KEYS: tuple[str, ...] = (
    PERM_SET_USERS_PENDING,
    PERM_SET_USERS_WHITELIST,
    PERM_SET_USERS_ALL,
    PERM_SET_USERS_ROLES,
    PERM_SET_USERS_IMPERSONATE,
    PERM_SET_USERS_FEEDBACK,
    PERM_SET_USERS_EVALUATION,
)
SET_SYSTEM_KEYS: tuple[str, ...] = (PERM_SET_SYSTEM, PERM_MAINTENANCE_ACCESS)
SET_MASCOT_KEYS: tuple[str, ...] = (PERM_SET_MASCOT,)
SET_EVENT_KEYS: tuple[str, ...] = (PERM_SET_EVENT,)
SET_CAMPUS_KEYS: tuple[str, ...] = (PERM_SET_CAMPUS,)

SETTINGS_KEYS: tuple[str, ...] = (
    SET_TOOLS_KEYS
    + SET_AIA_KEYS
    + SET_STATS_KEYS
    + SET_PROVIDER_KEYS
    + SET_USER_KEYS
    + SET_SYSTEM_KEYS
    + SET_MASCOT_KEYS
    + SET_EVENT_KEYS
    + SET_CAMPUS_KEYS
)

# === The whole catalogue =====================================================
ALL_PERMISSION_KEYS: tuple[str, ...] = GENERAL_KEYS + AIA_KEYS + TOOL_KEYS + SETTINGS_KEYS

# Chapter, group and rows in display order, everything else is derived.
MATRIX_LAYOUT: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (CHAPTER_USE, GROUP_GENERAL, GENERAL_KEYS),
    (CHAPTER_USE, GROUP_AIA, AIA_KEYS),
    (CHAPTER_USE, GROUP_TOOLS, TOOL_KEYS),
    (CHAPTER_MANAGE, GROUP_SET_TOOLS, SET_TOOLS_KEYS),
    (CHAPTER_MANAGE, GROUP_SET_AIA, SET_AIA_KEYS),
    (CHAPTER_MANAGE, GROUP_SET_STATS, SET_STATS_KEYS),
    (CHAPTER_MANAGE, GROUP_SET_PROVIDERS, SET_PROVIDER_KEYS),
    (CHAPTER_MANAGE, GROUP_SET_USERS, SET_USER_KEYS),
    (CHAPTER_MANAGE, GROUP_SET_SYSTEM, SET_SYSTEM_KEYS),
    (CHAPTER_MANAGE, GROUP_SET_MASCOT, SET_MASCOT_KEYS),
    (CHAPTER_MANAGE, GROUP_SET_EVENT, SET_EVENT_KEYS),
    (CHAPTER_MANAGE, GROUP_SET_CAMPUS, SET_CAMPUS_KEYS),
)

GROUPS: tuple[str, ...] = tuple(group for _, group, _ in MATRIX_LAYOUT)

GROUP_CHAPTER: dict[str, str] = {group: chapter for chapter, group, _ in MATRIX_LAYOUT}

PERMISSION_GROUPS: dict[str, tuple[str, ...]] = {
    group: keys for _, group, keys in MATRIX_LAYOUT
}

# Which key belongs to which module, everything else counts as always present.
KEY_MODULE: dict[str, str] = {
    **{k: MODULE_AIA for k in AIA_KEYS},
    PERM_SET_AIA_SOURCES: MODULE_AIA,
    PERM_SET_AIA_LEVEL: MODULE_AIA,
    PERM_SET_AIA_USAGE: MODULE_AIA,
    **{k: MODULE_TOOLS for k in TOOL_KEYS},
    # Own interfaces only feed the voice tools.
    PERM_GENERAL_INTERFACES: MODULE_TOOLS,
    PERM_SET_TOOLS_RELEASE: MODULE_TOOLS,
    PERM_SET_TOOLS_JOBS: MODULE_TOOLS,
    PERM_SET_TOOLS_LIMITS: MODULE_TOOLS,
    PERM_SET_TOOLS_STATS: MODULE_TOOLS,
    PERM_SET_CAMPUS: MODULE_TOOLS,
}


def keys_for_modules(modules) -> tuple[str, ...]:
    """The catalogue of this profile, in catalogue order."""
    aktiv = frozenset(modules)
    return tuple(
        k for k in ALL_PERMISSION_KEYS if KEY_MODULE.get(k) in (None, *aktiv)
    )


def matrix_layout_for(modules) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """The permission matrix of this profile, groups left empty drop out."""
    erlaubt = set(keys_for_modules(modules))
    gefiltert = []
    for chapter, group, keys in MATRIX_LAYOUT:
        uebrig = tuple(k for k in keys if k in erlaubt)
        if uebrig:
            gefiltert.append((chapter, group, uebrig))
    return tuple(gefiltert)


def is_settings_key(permission: str) -> bool:
    return permission.startswith(SETTINGS_PREFIX)


def valid_keys(keys) -> tuple[str, ...]:
    """Drops the unknown, restores catalogue order and deduplicates."""
    wanted = set(keys)
    return tuple(k for k in ALL_PERMISSION_KEYS if k in wanted)


# System roles are fixed in code, the table shows them greyed out.
SYSTEM_ROLES: tuple[str, ...] = ("admin", "staff", "user")

# Staff and user do not carry these, only admin or a custom role, and anyone handing out roles may grant them.
ROLE_ONLY_KEYS: tuple[str, ...] = (PERM_AIA_LANGUAGE_LEVEL,)

STAFF_AIA_KEYS: tuple[str, ...] = tuple(k for k in AIA_KEYS if k not in ROLE_ONLY_KEYS)

# Teachers read their modules' numbers on the module itself, students only get the learning assistant.
SYSTEM_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "admin": ALL_PERMISSION_KEYS,
    "staff": GENERAL_KEYS + STAFF_AIA_KEYS + TOOL_KEYS,
    "user": (PERM_AIA_USE,),
}

# Which settings field belongs to which right, unknown ones count as admin business.
SETTING_FIELD_PERMISSIONS: dict[str, str] = {
    "whitelist_enabled": PERM_SET_USERS_WHITELIST,
    "access_account_delete_after_days": PERM_SET_USERS_ALL,
    "screencast_max_slides": PERM_SET_TOOLS_LIMITS,
    "transcription_max_minutes": PERM_SET_TOOLS_LIMITS,
    "upload_max_mb": PERM_SET_TOOLS_LIMITS,
    "results_kept_per_user": PERM_SET_TOOLS_LIMITS,
    "tool_max_open_jobs": PERM_SET_TOOLS_LIMITS,
    "home_notice_enabled": PERM_SET_SYSTEM,
    "home_notice_text": PERM_SET_SYSTEM,
    "welcome_modal_enabled": PERM_SET_SYSTEM,
    "welcome_modal_text": PERM_SET_SYSTEM,
    "legal_contact_email": PERM_SET_SYSTEM,
    "legal_imprint_de": PERM_SET_SYSTEM,
    "legal_imprint_en": PERM_SET_SYSTEM,
    "legal_privacy_de": PERM_SET_SYSTEM,
    "legal_privacy_en": PERM_SET_SYSTEM,
    "language_training_enabled": PERM_SET_AIA_LEVEL,
    "ocr_enabled": PERM_SET_AIA_SOURCES,
    "aia_workspace_max_sources": PERM_SET_AIA_SOURCES,
    "aia_context_max_chars": PERM_SET_AIA_SOURCES,
    "aia_specific_max_chars": PERM_SET_AIA_SOURCES,
    "aia_tool_context_max_chars": PERM_SET_AIA_SOURCES,
    "aia_learning_tools_language": PERM_SET_AIA_SOURCES,
    "aia_summary_batch_max_chars": PERM_SET_AIA_SOURCES,
    "aia_source_max_pages": PERM_SET_AIA_SOURCES,
    "aia_flashcard_voice_provider_id": PERM_SET_PROVIDERS,
    "aia_flashcard_voice_id": PERM_SET_PROVIDERS,
    "tts_max_chars_per_request": PERM_SET_PROVIDERS,
    "language_diagnosis_prompt": PERM_SET_AIA_LEVEL,
    "language_diagnosis_question_plan_de": PERM_SET_AIA_LEVEL,
    "language_diagnosis_answer_max_chars": PERM_SET_AIA_LEVEL,
    "language_diagnosis_adaptive_behavior": PERM_SET_AIA_LEVEL,
    "language_diagnosis_grading_rules": PERM_SET_AIA_LEVEL,
    "language_diagnosis_level_examples": PERM_SET_AIA_LEVEL,
    "language_diagnosis_level_descriptions": PERM_SET_AIA_LEVEL,
}
