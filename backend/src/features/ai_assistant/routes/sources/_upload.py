"""Source upload / retry / delete."""
import asyncio
import tempfile
import time
import uuid

from src.core.redis_url import REDIS_URL
from src.security.rate_limit import check_upload_limit, record_upload
from src.utils.file_validation import validate_or_raise
from src.utils.upload_stream import stream_upload_to_path

from ._shared import (
    Path, APIRouter, Depends, File, HTTPException, UploadFile, logger, db,
    get_current_user, get_locale, t,
    AIA_MAX_CONCURRENT_UPLOADS,
    delete_aia_source_files,
    _convert_office_to_pdf_path, _mp4_faststart_path,
    _require_workspace_manage, _load_workspace_source,
    _require_source_capacity, _register_source_file,
    _workspace_label, _enqueue_index_source,
    _ALLOWED_EXTENSIONS,
)

router = APIRouter(tags=["ki-assistent: sources"])

# Global upload brake in Redis, as a sorted set with timestamps.
_UPLOAD_SET_KEY = "askf:uploads:inflight"
# How long a slot is valid at most, an orphan heals by itself afterwards.
_UPLOAD_STALE_SECONDS = 15 * 60



def _redis():
    """Redis client with short timeouts, same pattern as rate_limit.py."""
    import redis as _redis_lib
    return _redis_lib.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1)


def _max_concurrent_uploads() -> int:
    """How many uploads may pass through the heavy phase at once."""
    return AIA_MAX_CONCURRENT_UPLOADS


def _claim_upload_slot(limit: int) -> str | None:
    """Claims an upload slot, or None when full."""
    ticket = uuid.uuid4().hex
    now = time.time()
    try:
        r = _redis()
        pipe = r.pipeline()
        pipe.zremrangebyscore(_UPLOAD_SET_KEY, "-inf", now - _UPLOAD_STALE_SECONDS)
        pipe.zcard(_UPLOAD_SET_KEY)
        in_flight = pipe.execute()[1]
        if 0 < limit <= in_flight:
            return None
        r.zadd(_UPLOAD_SET_KEY, {ticket: now})
        return ticket
    except Exception as e:
        logger.warning("Upload-Bremse nicht erreichbar (Redis), lasse durch: {}", e)
        return ticket


# How long an upload waits for a free slot, well below the 60 s silence nginx allows by default.
_UPLOAD_SLOT_WAIT_SECONDS = 30


async def _wait_for_upload_slot(limit: int, wait_seconds: float | None = None) -> str | None:
    """Waits a while for a free slot, the file is already here and a refusal would send it again."""
    wait_seconds = _UPLOAD_SLOT_WAIT_SECONDS if wait_seconds is None else wait_seconds
    start = time.monotonic()
    while True:
        ticket = _claim_upload_slot(limit)
        if ticket is not None:
            return ticket
        if time.monotonic() - start >= wait_seconds:
            return None
        await asyncio.sleep(1.0)


def _release_upload_slot(ticket: str) -> None:
    try:
        _redis().zrem(_UPLOAD_SET_KEY, ticket)
    except Exception as e:
        # No drama: the entry drops out by itself after _UPLOAD_STALE_SECONDS.
        logger.warning("Upload-Platz konnte nicht freigegeben werden: {}", e)




@router.post("/ai-assistant/workspaces/{workspace_uuid}/sources")
async def upload_source(
    workspace_uuid: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    workspace = _require_workspace_manage(workspace_uuid, current_user["user_id"], locale=locale)

    # Only check, do not count, so a rejection uses up no slot.
    check_upload_limit(current_user["user_id"], locale=locale)

    existing_sources = db.get_aia_sources_by_workspace(workspace["id"])
    # Existing filenames, normalized for a case-insensitive duplicate check below.
    existing_names = {(s["filename"] or "").strip().lower() for s in existing_sources}

    _require_source_capacity(existing_sources, locale)

    if not file.filename:
        raise HTTPException(status_code=400, detail=t("file.nameMissing", locale))
    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=t("ai.source.allowedExtensions", locale, extensions=", ".join(sorted(_ALLOWED_EXTENSIONS))),
        )

    # Reject same-named uploads early, office files are checked again after conversion.
    if file.filename.strip().lower() in existing_names:
        raise HTTPException(
            status_code=409,
            detail=t("ai.source.duplicateName", locale, name=file.filename, label=_workspace_label(locale)),
        )

    # Whoever gets no slot in time receives 503, the page then sends the file again by itself.
    ticket = await _wait_for_upload_slot(_max_concurrent_uploads())
    if ticket is None:
        raise HTTPException(status_code=503, detail=t("ai.source.serverBusy", locale))
    try:
        # Stream onto a temp file and keep every heavy step outside the event loop.
        with tempfile.TemporaryDirectory(prefix="aia_upload_") as tmpdir:
            raw_path = str(Path(tmpdir) / f"input{ext}")
            # The same size the tools use, one setting for the whole platform.
            from src.services.tool_limits import max_upload_bytes
            total, head = await stream_upload_to_path(file, raw_path, max_upload_bytes(), locale)
            if total == 0:
                raise HTTPException(status_code=400, detail=t("file.empty", locale))
            validate_or_raise(head, ext, locale)

            stored_filename = file.filename
            final_path = raw_path
            if ext in (".docx", ".pptx"):
                logger.info("KI Tutor: converting {} to PDF ({})", ext, file.filename)
                final_path = await asyncio.to_thread(_convert_office_to_pdf_path, raw_path, ext, tmpdir, locale)
                stored_filename = Path(file.filename).stem + ".pdf"
                ext = ".pdf"
                # The converted name can now collide with an existing source.
                if stored_filename.strip().lower() in existing_names:
                    raise HTTPException(
                        status_code=409,
                        detail=t("ai.source.duplicateName", locale, name=stored_filename, label=_workspace_label(locale)),
                    )
            elif ext == ".mp4":
                logger.info("KI Tutor: applying MP4 faststart ({})", file.filename)
                final_path = await asyncio.to_thread(_mp4_faststart_path, raw_path, tmpdir)

            result = await _register_source_file(
                workspace, workspace_uuid, final_path, ext, stored_filename, current_user["user_id"], locale,
            )

            # Only count now, every rejection above reversed it before.
            record_upload(current_user["user_id"])

            logger.info("KI Tutor: source {} ({}) uploaded to workspace {}", result["uuid"], stored_filename, workspace_uuid)
            return result
    finally:
        _release_upload_slot(ticket)


@router.post("/ai-assistant/workspaces/{workspace_uuid}/sources/{source_uuid}/retry")
def retry_source(
    workspace_uuid: str,
    source_uuid: str,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    workspace = _require_workspace_manage(workspace_uuid, current_user["user_id"], locale=locale)
    # Binds the source to your own course room.
    source = _load_workspace_source(source_uuid, workspace, locale)
    # Two ways in: a broken source or one with open pages.
    ocr_open = bool((source.get("ocr_info") or {}).get("open"))
    catching_up_ocr = source["status"] == "ready" and ocr_open
    if source["status"] != "failed" and not catching_up_ocr:
        raise HTTPException(status_code=409, detail=t("ai.source.retryFailedOnly", locale))

    # Only the summary failed, so retry resumes there and keeps chunks and vectors.
    if source["status"] == "failed" and source.get("file_type") != "text" \
            and not (source.get("summary") or "").strip():
        total, unembedded = db.count_chunks_and_unembedded(source["id"])
        if total > 0 and unembedded == 0:
            from src.features.ai_assistant.tasks.ingestion import run_summarize_source
            db.resume_aia_source_summary(source_uuid)
            try:
                run_summarize_source.delay(source_uuid, locale)
            except Exception:
                db.update_aia_source_status(source_uuid, "failed")
                raise
            logger.info("KI Tutor: source {} resumes at the summary", source_uuid)
            return {"uuid": source_uuid, "status": "indexing"}

    db.delete_aia_chunks_by_source(source["id"])
    db.reset_aia_source_for_retry(source_uuid)

    _enqueue_index_source(source_uuid, current_user["user_id"], locale)

    logger.info("KI Tutor: source {} retry dispatched", source_uuid)
    return {"uuid": source_uuid, "status": "pending"}


@router.delete("/ai-assistant/workspaces/{workspace_uuid}/sources/{source_uuid}")
def delete_source(
    workspace_uuid: str,
    source_uuid: str,
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    workspace = _require_workspace_manage(workspace_uuid, current_user["user_id"], locale=locale)
    # Binds the source to your own course room.
    source = _load_workspace_source(source_uuid, workspace, locale)
    try:
        delete_aia_source_files(source["file_path"])
    except Exception as e:
        logger.warning("KI Tutor: could not delete source files for {}: {}", source["file_path"], e)
    db.delete_aia_source(source_uuid)
    logger.info("KI Tutor: source {} deleted", source_uuid)
    return {"deleted": source_uuid}
