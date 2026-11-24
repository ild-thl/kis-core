"""KI-Assistent routes - workspace CRUD, access links, enrollment."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException
from loguru import logger


from src import database as db
from src.dependencies import get_current_user
from src.i18n import (
    DEFAULT_DIAGNOSIS_LANGUAGE,
    DEFAULT_TRANSCRIPT_TARGET,
    TRANSCRIPT_LANGUAGES,
    get_locale,
    t,
)
from src.limits import (
    AIA_WORKSPACE_MAX_ACCESS_LINKS,
    AIA_WORKSPACE_MAX_MEMBERS,
    AIA_TEXT_SOURCE_MAX_CHARS,
)

from src.features.ai_assistant.routes._workspace_access import (
    _delete_workspace_files,
    _require_workspace_access,
    _require_workspace_manage,
    _require_workspace_owner,
)
from src.dependencies_rbac import require_workspace_create
from src.features.ai_assistant import schemas

router = APIRouter(tags=["ki-assistent: workspaces"])


def _parse_optional_expiry(raw: str | None, locale: str) -> datetime | None:
    """Turn an ISO string into a UTC datetime. Empty or missing means never expires."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail=t("date.invalidExpiresAt", locale))


def _iso_z(moment: datetime | None) -> str | None:
    """A UTC moment as the browser reads it, an offset would make the trailing Z invalid."""
    return moment.replace(tzinfo=None).isoformat() + "Z" if moment else None


def _link_payload(link: dict) -> dict:
    """One access link as the browser sees it."""
    return {
        "id": link["id"],
        "code": link["code"],
        "expires_at": _iso_z(link["expires_at"]),
        "created_at": _iso_z(link["created_at"]),
    }


def _legacy_enroll_fields(links: list[dict], row: dict) -> dict:
    """The old single-code fields, taken from the first link when there is one."""
    if links:
        return {"enroll_code": links[0]["code"],
                "enroll_code_expires": _iso_z(links[0]["expires_at"])}
    return {"enroll_code": row.get("enroll_code"),
            "enroll_code_expires": _iso_z(row.get("enroll_code_expires"))}


@router.post(
    "/ai-assistant/workspaces",
    dependencies=[Depends(require_workspace_create)],
)
def create_workspace(
    title: str = Form(..., max_length=100),
    description: Optional[str] = Form(None, max_length=500),
    expires_at: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    user_id = current_user["user_id"]
    # Checked first, a bad date must not leave a workspace without a link behind.
    expires = _parse_optional_expiry(expires_at, locale)
    workspace_uuid = db.create_aia_workspace(user_id, title, description)

    # Create first access link
    enroll_code = uuid.uuid4().hex[:8]
    workspace = db.get_aia_workspace(workspace_uuid)
    link = db.create_access_link(workspace["id"], enroll_code, expires)
    # Also set legacy fields for backward compat
    db.set_aia_workspace_enroll_code(workspace_uuid, enroll_code, expires)

    logger.info("KI Tutor: workspace {} created by user {}", workspace_uuid, user_id)
    return {
        "uuid": workspace_uuid,
        "title": title,
        "access_links": [{
            "id": link["id"],
            "code": link["code"],
            "expires_at": _iso_z(link["expires_at"]),
        }],
        # Legacy fields
        "enroll_code": enroll_code,
        "enroll_code_expires": _iso_z(expires),
    }


def _managed_workspace_payload(m: dict, access: str, shared: bool, favorite: bool) -> dict:
    """Row for someone who manages the course room, owner or tutor."""
    sources = db.get_aia_sources_by_workspace(m["id"])
    links = db.get_access_links_by_workspace(m["id"])
    return {
        "uuid": m["uuid"],
        "title": m["title"],
        "description": m["description"],
        "status": m["status"],
        "is_active": m["is_active"],
        "access": access,
        "shared": shared,
        "is_favorite": favorite,
        "is_demo_workspace": bool(m.get("owner_is_demo")),
        "is_tour_module": bool(m.get("is_tour_module")),
        "source_count": len(sources),
        "member_count": db.count_enrollments(m["id"]),
        "access_links": [_link_payload(l) for l in links],
        # Legacy: first link as enroll_code for backward compat
        **_legacy_enroll_fields(links, m),
        "created_at": m["created_at"].isoformat() + "Z" if m["created_at"] else None,
    }


@router.get("/ai-assistant/workspaces")
def list_workspaces(current_user: dict = Depends(get_current_user)):
    """All reachable course rooms in one list, with the kind of access."""
    user_id = current_user["user_id"]
    with_tutors = db.get_workspace_ids_with_tutors()
    favorite_ids = db.get_favorite_workspace_ids(user_id)
    result = []

    for m in db.get_aia_workspaces_by_user(user_id):
        result.append(_managed_workspace_payload(m, "owner", m["id"] in with_tutors, m["id"] in favorite_ids))

    owned_ids = {m["uuid"] for m in result}
    seen_as_tutor: set[str] = set()
    for m in db.get_aia_workspaces_for_member(user_id):
        if m["uuid"] in owned_ids:
            continue  # owner who also holds an enrollment, ownership already covers it
        if m.get("member_role") == "tutor":
            if m["uuid"] in seen_as_tutor:
                continue  # enrolled through several links, still one workspace
            seen_as_tutor.add(m["uuid"])
            result.append(_managed_workspace_payload(m, "tutor", True, m["id"] in favorite_ids))
            continue
        result.append({
            "uuid": m["uuid"],
            "title": m["title"],
            "description": m["description"],
            "status": m["status"],
            "is_active": m["is_active"],
            "access": "student",
            "shared": False,
            "is_favorite": m["id"] in favorite_ids,
            "source_count": len(db.get_aia_sources_by_workspace(m["id"])),
            "enrollment_id": m.get("enrollment_id"),
            "enrolled_until": m["enrolled_until"].isoformat() + "Z" if m.get("enrolled_until") else None,
            "created_at": m["created_at"].isoformat() + "Z" if m["created_at"] else None,
            # Joined through the demo or through a real link.
            "via_demo": bool(m.get("via_demo")),
        })

    # The stronger role wins, otherwise the row would appear twice.
    result = [r for r in result if not (r["access"] == "student" and r["uuid"] in seen_as_tutor)]
    return result

@router.patch("/ai-assistant/workspaces/{workspace_uuid}/favorite")
def patch_workspace_favorite(
    workspace_uuid: str,
    body: schemas.FavoriteWorkspaceBody,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    """Starring works for owner, tutor and enrolled alike, it is purely per-user."""
    workspace = _require_workspace_access(workspace_uuid, current_user["user_id"], locale=locale)
    db.set_workspace_favorite(current_user["user_id"], workspace["id"], body.favorite)
    return {"is_favorite": body.favorite}

@router.get("/ai-assistant/transcript-languages")
def list_transcript_languages(
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    """The languages that can be translated into, from i18n.TRANSCRIPT_LANGUAGES."""
    languages = [
        {"id": code, "deepl": meta["deepl"], "label": t(f"lang.{meta['deepl']}", locale)}
        for code, meta in TRANSCRIPT_LANGUAGES.items()
    ]
    return {"languages": languages, "default": DEFAULT_TRANSCRIPT_TARGET}


@router.get("/ai-assistant/workspaces/{workspace_uuid}")
def get_workspace(
    workspace_uuid: str,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    workspace = _require_workspace_access(workspace_uuid, current_user["user_id"], locale=locale)
    is_owner = workspace["user_id"] == current_user["user_id"]
    if is_owner:
        db.touch_aia_workspace_visited(workspace_uuid)
    sources = db.get_aia_sources_by_workspace(workspace["id"])
    chapters = db.get_aia_chapters_by_workspace(workspace["id"])
    # Only the chapter's uuid goes outside, never the internal id.
    chapter_uuid_by_id = {c["id"]: c["uuid"] for c in chapters}
    links = db.get_access_links_by_workspace(workspace["id"])
    # The interface follows can_manage, is_owner stays pure ownership.
    can_manage = is_owner or db.is_workspace_tutor(workspace["id"], current_user["user_id"])
    # Only the demo course offers enrolled people the read-only owner preview.
    owner = db.get_user_by_id(workspace["user_id"])
    return {
        "uuid": workspace["uuid"],
        "title": workspace["title"],
        "description": workspace["description"],
        "status": workspace["status"],
        "is_active": workspace["is_active"],
        "is_owner": is_owner,
        "can_manage": can_manage,
        "is_demo_workspace": bool(owner and owner.get("is_demo")),
        "is_tour_module": bool(workspace.get("is_tour_module")),
        "transcript_target_lang": workspace.get("transcript_target_lang", "en"),
        "diagnosis_language": workspace.get("diagnosis_language", DEFAULT_DIAGNOSIS_LANGUAGE),
        # Without the admin switch the catch-up entry would be a dead end.
        "ocr_enabled": db.get_setting("ocr_enabled", "true").lower() == "true",
        "text_source_max_chars": AIA_TEXT_SOURCE_MAX_CHARS,
        "staff_note_text": workspace.get("staff_note_text"),
        "staff_note_links": workspace.get("staff_note_links") or [],
        "access_links": [_link_payload(l) for l in links],
        **_legacy_enroll_fields(links, workspace),
        "created_at": workspace["created_at"].isoformat() + "Z" if workspace["created_at"] else None,
        "chapters": [
            {"uuid": c["uuid"], "name": c["name"], "position": c["position"]}
            for c in chapters
        ],
        "sources": [
            {
                "uuid": s["uuid"],
                "filename": s["filename"],
                "status": s["status"],
                "chunk_count": s["chunk_count"],
                "error_message": s.get("error_message"),
                "progress": s.get("progress"),
                "ocr_info": s.get("ocr_info"),
                "source_url": s.get("source_url"),
                "file_type": s.get("file_type"),
                # Only whether there is one, the text itself is fetched when opened.
                "has_summary": bool((s.get("summary") or "").strip()),
                "chapter_uuid": chapter_uuid_by_id.get(s.get("chapter_id")),
                "created_at": s["created_at"].isoformat() + "Z" if s["created_at"] else None,
            }
            for s in sources
        ],
    }

def _dispatch_transcript_retranslation(workspace: dict, target_lang: str) -> None:
    """Re-translates every finished media source of the course room, owner only."""
    from src.services import feature_router, aia_chunker
    try:
        binding = feature_router.resolve("transcript_translate")
    except feature_router.FeatureNotConfigured:
        logger.warning(
            "KI Tutor: target changed but transcript_translate not configured (workspace {})",
            workspace["uuid"],
        )
        return
    from src.tasks.aia_tasks import run_translate_transcript
    dispatched = 0
    for s in db.get_aia_sources_by_workspace(workspace["id"]):
        if s.get("status") != "ready" or not aia_chunker.is_media_file(s.get("file_type") or ""):
            continue
        run_translate_transcript.delay(s["uuid"], binding.provider["id"], target_lang)
        dispatched += 1
    logger.info(
        "KI Tutor: dispatched re-translation to '{}' for {} media source(s) in workspace {}",
        target_lang, dispatched, workspace["uuid"],
    )


@router.patch("/ai-assistant/workspaces/{workspace_uuid}")
def patch_workspace(
    workspace_uuid: str,
    body: schemas.PatchWorkspaceBody,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    workspace = _require_workspace_manage(workspace_uuid, current_user["user_id"], locale=locale)
    new_title = body.title if body.title is not None else workspace["title"]
    new_desc = body.description if body.description is not None else workspace["description"]
    new_active = body.is_active if body.is_active is not None else workspace["is_active"]
    db.update_aia_workspace(workspace_uuid, new_title, new_desc, new_active)
    if body.is_tour_module is not None:
        owner = db.get_user_by_id(workspace["user_id"])
        # The tour's stations point at the demo files, any other course leads nowhere.
        if not (owner and owner.get("is_demo")):
            raise HTTPException(status_code=400, detail=t("ai.workspace.tourModuleNotDemo", locale))
        db.set_aia_workspace_tour_module(workspace_uuid, body.is_tour_module)
    if body.transcript_target_lang is not None:
        if body.transcript_target_lang not in TRANSCRIPT_LANGUAGES:
            raise HTTPException(status_code=400, detail=t("ai.workspace.transcriptTargetLangInvalid", locale))
        prev_target = workspace.get("transcript_target_lang", "en")
        db.set_aia_workspace_transcript_target_lang(workspace_uuid, body.transcript_target_lang)
        # Changing the target language re-translates existing media sources.
        if body.transcript_target_lang != prev_target:
            _dispatch_transcript_retranslation(workspace, body.transcript_target_lang)
    if body.diagnosis_language is not None:
        if body.diagnosis_language not in TRANSCRIPT_LANGUAGES:
            raise HTTPException(status_code=400, detail=t("ai.workspace.diagnosisLanguageInvalid", locale))
        db.set_aia_workspace_diagnosis_language(workspace_uuid, body.diagnosis_language)
    if body.staff_note_text is not None or body.staff_note_links is not None:
        new_text = body.staff_note_text if body.staff_note_text is not None else workspace.get("staff_note_text")
        new_links_models = body.staff_note_links if body.staff_note_links is not None else []
        new_links = [{"url": l.url, "label": l.label} for l in new_links_models] if body.staff_note_links is not None else (workspace.get("staff_note_links") or [])
        db.set_aia_workspace_staff_note(workspace_uuid, new_text, new_links)
    return {"uuid": workspace_uuid, "title": new_title, "is_active": new_active}

@router.patch("/ai-assistant/workspaces/{workspace_uuid}/renew-code")
def renew_enroll_code(
    workspace_uuid: str,
    body: schemas.RenewCodeBody,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    """Legacy: creates a new access link (kept for backward compat)."""
    workspace = _require_workspace_manage(workspace_uuid, current_user["user_id"], locale=locale)
    expires = _parse_optional_expiry(body.expires_at, locale)
    new_code = uuid.uuid4().hex[:8]
    link = db.create_access_link(workspace["id"], new_code, expires)
    db.set_aia_workspace_enroll_code(workspace_uuid, new_code, expires)
    logger.info("KI Tutor: access link created for workspace {}", workspace_uuid)
    return {
        "enroll_code": new_code,
        "enroll_code_expires": _iso_z(expires),
        "link_id": link["id"],
    }


# ─── Access Links ────────────────────────────────────────────────────────────

@router.post("/ai-assistant/workspaces/{workspace_uuid}/access-links")
def create_workspace_access_link(
    workspace_uuid: str,
    body: schemas.CreateAccessLinkBody,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    workspace = _require_workspace_manage(workspace_uuid, current_user["user_id"], locale=locale)
    existing_links = db.get_access_links_by_workspace(workspace["id"])
    if len(existing_links) >= AIA_WORKSPACE_MAX_ACCESS_LINKS:
        raise HTTPException(
            status_code=400,
            detail=t("ai.workspace.maxAccessLinks", locale, max=AIA_WORKSPACE_MAX_ACCESS_LINKS),
        )
    expires = _parse_optional_expiry(body.expires_at, locale)
    code = uuid.uuid4().hex[:8]
    link = db.create_access_link(workspace["id"], code, expires)
    logger.info("KI Tutor: access link {} created for workspace {}", link["id"], workspace_uuid)
    return {
        "id": link["id"],
        "code": link["code"],
        "expires_at": _iso_z(link["expires_at"]),
    }

@router.get("/ai-assistant/workspaces/{workspace_uuid}/access-links")
def list_access_links(
    workspace_uuid: str,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    workspace = _require_workspace_manage(workspace_uuid, current_user["user_id"], locale=locale)
    links = db.get_access_links_by_workspace(workspace["id"])
    return [_link_payload(l) for l in links]

@router.delete("/ai-assistant/workspaces/{workspace_uuid}/access-links/{link_id}")
def delete_access_link(
    workspace_uuid: str,
    link_id: int,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    workspace = _require_workspace_manage(workspace_uuid, current_user["user_id"], locale=locale)
    db.delete_access_link(link_id, workspace["id"])
    logger.info("KI Tutor: access link {} deleted from workspace {}", link_id, workspace_uuid)
    return {"deleted": link_id}

@router.delete("/ai-assistant/workspaces/{workspace_uuid}")
def delete_workspace(
    workspace_uuid: str,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    workspace = _require_workspace_owner(workspace_uuid, current_user["user_id"], locale=locale)
    _delete_workspace_files(workspace)
    db.delete_aia_workspace(workspace_uuid)
    logger.info("KI Tutor: workspace {} deleted by user {}", workspace_uuid, current_user["user_id"])
    return {"deleted": workspace_uuid}

@router.get("/ai-assistant/workspaces/{workspace_uuid}/participants")
def list_participants(
    workspace_uuid: str,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    """Who is in this workspace. Owner and tutors may look, only the owner may change."""
    workspace = _require_workspace_manage(workspace_uuid, current_user["user_id"], locale=locale)
    is_owner = workspace["user_id"] == current_user["user_id"]
    return {
        "can_edit": is_owner,
        "participants": [
            {
                "user_id": p["user_id"],
                "display_name": p["display_name"],
                "username": p["username"],
                "role": "tutor" if p["is_tutor"] else "student",
                "joined_at": p["joined_at"].isoformat() + "Z" if p["joined_at"] else None,
                "enrolled_until": p["enrolled_until"].isoformat() + "Z" if p["enrolled_until"] else None,
            }
            for p in db.get_workspace_participants(workspace["id"])
        ],
    }


@router.patch("/ai-assistant/workspaces/{workspace_uuid}/participants/{user_id}")
def set_participant_role(
    workspace_uuid: str,
    user_id: int,
    body: schemas.SetParticipantRoleBody,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    """Makes someone a tutor or takes it back, owner only."""
    workspace = _require_workspace_owner(workspace_uuid, current_user["user_id"], locale=locale)
    if user_id == workspace["user_id"]:
        # The owner is not a participant and cannot demote themselves into one.
        raise HTTPException(status_code=400, detail=t("workspace.accessDenied", locale))
    geaendert = db.set_participant_role(workspace["id"], user_id, body.role)
    if not geaendert:
        raise HTTPException(status_code=404, detail=t("workspace.notFound", locale))
    logger.info(
        "KI Tutor: user {} set to {} in workspace {} by owner {}",
        user_id, body.role, workspace_uuid, current_user["user_id"],
    )
    return {"user_id": user_id, "role": body.role}


def _is_open_for(workspace: dict, user_id: int) -> bool:
    """Whether this person may enter the course room right now."""
    if workspace.get("is_active", True):
        return True
    if workspace["user_id"] == user_id:
        return True
    return db.is_workspace_tutor(workspace["id"], user_id)


def _einschreibe_karte(workspace: dict, gueltig_bis, user_id: int) -> dict:
    """Everything shown on the card before enrolling, from one place."""
    owner = db.get_user_by_id(workspace["user_id"])
    return {
        "workspace_uuid": workspace["uuid"],
        "title": workspace["title"],
        "description": workspace.get("description") or None,
        "owner_name": owner["display_name"] if owner else None,
        "access_until": gueltig_bis.isoformat() + "Z" if gueltig_bis else None,
        "is_open": _is_open_for(workspace, user_id),
    }


@router.get("/ai-assistant/access-link/preview")
def preview_access_link(
    code: str,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    user_id = current_user["user_id"]
    result = db.get_workspace_by_access_link_code(code)
    if result:
        workspace, link = result
        return _einschreibe_karte(workspace, link["expires_at"], user_id)
    workspace = db.get_workspace_by_enroll_code(code)
    if not workspace:
        raise HTTPException(status_code=404, detail=t("ai.workspace.invalidEnrollCode", locale))
    # On the old path the deadline hangs off the workspace instead of a link.
    return _einschreibe_karte(workspace, workspace.get("enroll_code_expires"), user_id)

@router.post("/ai-assistant/enroll")
def enroll(
    body: schemas.EnrollBody,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    user_id = current_user["user_id"]

    # Joining a closed course room is allowed, is_open says so.

    # Try new access_links table first
    result = db.get_workspace_by_access_link_code(body.enroll_code)
    if result:
        workspace, link = result
        offen = _is_open_for(workspace, user_id)
        # The owner following their own link stays the owner, nothing to join.
        if workspace["user_id"] == user_id:
            return {"workspace_uuid": workspace["uuid"], "title": workspace["title"], "enrollment_id": None, "is_open": offen}
        # The question is about the course, not the link, otherwise it appears twice.
        existing = db.get_enrollment(workspace["id"], user_id)
        if existing:
            return {"workspace_uuid": workspace["uuid"], "title": workspace["title"], "enrollment_id": existing["id"], "is_open": offen}
        if db.count_enrollments(workspace["id"]) >= AIA_WORKSPACE_MAX_MEMBERS:
            raise HTTPException(
                status_code=409,
                detail=t("ai.workspace.maxMembers", locale, max=AIA_WORKSPACE_MAX_MEMBERS),
            )
        # Every link joins as a learner, tutor rights are granted by the owner.
        enrollment_id = db.enroll_student(
            workspace["id"], user_id, link["expires_at"], link_id=link["id"],
        )
        if not enrollment_id:
            # Already enrolled (race condition) - fetch existing
            existing = db.get_enrollment(workspace["id"], user_id)
            return {"workspace_uuid": workspace["uuid"], "title": workspace["title"], "enrollment_id": existing["id"] if existing else None, "is_open": offen}
        logger.info("KI Tutor: user {} enrolled in workspace {} via link {}", user_id, workspace["uuid"], link["id"])
        return {"workspace_uuid": workspace["uuid"], "title": workspace["title"], "enrollment_id": enrollment_id, "is_open": offen}

    # Fallback: legacy enroll_code on workspace
    workspace = db.get_workspace_by_enroll_code(body.enroll_code)
    if not workspace:
        raise HTTPException(status_code=404, detail=t("ai.workspace.invalidEnrollCode", locale))
    offen = _is_open_for(workspace, user_id)
    if db.is_student_enrolled(workspace["id"], user_id):
        return {"workspace_uuid": workspace["uuid"], "title": workspace["title"], "is_open": offen}
    if db.count_enrollments(workspace["id"]) >= AIA_WORKSPACE_MAX_MEMBERS:
        raise HTTPException(
            status_code=409,
            detail=t("ai.workspace.maxMembers", locale, max=AIA_WORKSPACE_MAX_MEMBERS),
        )
    enrolled_until = workspace.get("enroll_code_expires")
    db.enroll_student(workspace["id"], user_id, enrolled_until)
    logger.info("KI Tutor: user {} enrolled in workspace {} (legacy)", user_id, workspace["uuid"])
    return {"workspace_uuid": workspace["uuid"], "title": workspace["title"], "is_open": offen}

@router.get("/ai-assistant/my-workspaces")
def my_workspaces(current_user: dict = Depends(get_current_user)):
    """Old: only the course rooms the person learns from, replaced by the full list."""
    workspaces = [
        m for m in db.get_aia_workspaces_for_student(current_user["user_id"])
        if m.get("role", "student") != "tutor"
    ]
    return [
        {
            "uuid": m["uuid"],
            "title": m["title"],
            "description": m["description"],
            "status": m["status"],
            "enrollment_id": m.get("enrollment_id"),
            "enrolled_until": m["enrolled_until"].isoformat() + "Z" if m.get("enrolled_until") else None,
            "created_at": m["created_at"].isoformat() + "Z" if m["created_at"] else None,
        }
        for m in workspaces
    ]

