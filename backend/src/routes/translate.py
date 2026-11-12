import asyncio
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from loguru import logger

from src import database as db
from src.dependencies import get_current_user, is_admin_user
from src.i18n import (
    DEFAULT_TRANSLATE_SOURCE,
    DEFAULT_TRANSLATE_TARGET,
    TRANSLATE_LANGUAGES,
    get_locale,
    t,
)
from src.quotas import enforce_quota
from src.security.rate_limit import enforce_tool_burst
from src.services.job_lanes import translate_route
from src.services.open_jobs import create_counted_job, enforce_open_jobs
from src.storage import save_queue_file_from_path
from src.services.tool_limits import max_upload_bytes
from src.utils.file_validation import (
    ALLOWED_EXTENSIONS,
    TRANSLATE_MAX_CHARS,
    sanitize_pasted_text,
    pages_or_raise,
    validate_or_raise,
)
from src.translators.latex_source import TEX_BYTES_PER_CHAR, tex_plain_text
from src.utils.text_extraction import EXTRACTORS
from src.utils.upload_stream import stream_upload_to_path
from src.dependencies_rbac import require_tool_access

router = APIRouter(
    tags=["translate"],
    dependencies=[Depends(require_tool_access("translation"))],
)

@router.get("/translate/config")
async def get_translate_config(
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    from src.dependencies import get_translation_providers
    from src.services.feature_provider_choices import only_reachable
    raw_providers = await only_reachable(get_translation_providers(), "chat")
    providers = [{"id": p["id"], "label": p["name"]} for p in raw_providers]
    return {"providers": providers, **_languages(locale)}


@router.get("/translate/providers")
async def get_translate_providers(current_user: dict = Depends(get_current_user)):
    """The reachable providers alone, in the shape every provider dropdown loads."""
    from src.dependencies import get_translation_providers
    from src.services.feature_provider_choices import only_reachable
    providers = await only_reachable(get_translation_providers(), "chat")
    return {
        "providers": [{"id": p["id"], "name": p["name"]} for p in providers],
        "default_id": providers[0]["id"] if providers else None,
    }


@router.get("/translate/languages")
def get_translate_languages(
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    """The languages alone, so a page does not wait for the provider checks."""
    return _languages(locale)


def _languages(locale: str) -> dict:
    """The target languages with their defaults."""
    return {
        "languages": [{"id": lang, "label": t(f"lang.{lang}", locale)} for lang in TRANSLATE_LANGUAGES],
        "default_source": DEFAULT_TRANSLATE_SOURCE,
        "default_target": DEFAULT_TRANSLATE_TARGET,
    }


@router.post("/translate")
async def translate(
    request: Request,
    file: UploadFile | None = File(None),
    text: str = Form(""),
    glossary: str = Form(""),
    provider_id: int | None = Form(None),
    source_lang: str = Form(""),
    target_lang: str = Form(""),
    current_user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    has_file = bool(file and file.filename)
    has_text = bool(text and text.strip())
    if has_file and has_text:
        raise HTTPException(status_code=400, detail=t("translate.bothInputs", locale))
    if not has_file and not has_text:
        raise HTTPException(status_code=400, detail=t("translate.noInput", locale))

    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > max_upload_bytes():
        raise HTTPException(status_code=413, detail=t("file.tooLargeMb", locale, max=max_upload_bytes() // (1024 * 1024)))

    # Both inputs end up as a file, the upload never sits in memory.
    with tempfile.TemporaryDirectory(prefix="translate_upload_") as tmpdir:
        zeichen: int | None = None
        seiten: int | None = None
        if has_text:
            cleaned = sanitize_pasted_text(text)
            if not cleaned:
                raise HTTPException(status_code=400, detail=t("translate.textEmpty", locale))
            if len(cleaned) > TRANSLATE_MAX_CHARS:
                raise HTTPException(
                    status_code=422,
                    detail=t(
                        "translate.textTooLong",
                        locale,
                        chars=f"{len(cleaned):,}".replace(",", "."),
                        maxChars=f"{TRANSLATE_MAX_CHARS:,}".replace(",", "."),
                    ),
                )
            zeichen = len(cleaned)
            ext = ".txt"
            filename = "text.txt"
            tmp_path = os.path.join(tmpdir, "input.txt")
            with open(tmp_path, "wb") as out:
                out.write(cleaned.encode("utf-8"))
        else:
            assert file is not None
            if not file.filename:
                raise HTTPException(status_code=400, detail=t("file.nameMissing", locale))

            ext = Path(file.filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise HTTPException(status_code=400, detail=t("translate.unsupportedFormat", locale))

            tmp_path = os.path.join(tmpdir, f"input{ext}")
            total, head = await stream_upload_to_path(file, tmp_path, max_upload_bytes(), locale)
            if not total:
                raise HTTPException(status_code=400, detail=t("file.empty", locale))
            extracted: str | None = None
            if ext == ".tex":
                # Markup only adds bytes, so a file far above the text limit is refused before it is parsed.
                tex_max_bytes = TRANSLATE_MAX_CHARS * TEX_BYTES_PER_CHAR
                if total > tex_max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=t("file.tooLargeMb", locale, max=max(1, round(tex_max_bytes / (1024 * 1024)))),
                    )
                # LaTeX may come in any encoding and is counted as the translator will send it, only binary is refused.
                try:
                    extracted = await asyncio.to_thread(tex_plain_text, tmp_path)
                except ValueError:
                    raise HTTPException(status_code=400, detail=t("file.contentMismatch", locale)) from None
            else:
                validate_or_raise(head, ext, locale)
            seiten = await asyncio.to_thread(pages_or_raise, ext, tmp_path, locale)

            extractor = EXTRACTORS.get(ext)
            if extracted is None and extractor is not None:
                extracted = await asyncio.to_thread(extractor, tmp_path)
            if extracted is not None:
                zeichen = len(extracted)
                if len(extracted) > TRANSLATE_MAX_CHARS:
                    raise HTTPException(
                        status_code=422,
                        detail=t(
                            "translate.documentTooLong",
                            locale,
                            chars=f"{len(extracted):,}".replace(",", "."),
                            maxChars=f"{TRANSLATE_MAX_CHARS:,}".replace(",", "."),
                        ),
                    )
            filename = file.filename

        effective_source = source_lang or ""
        effective_target = target_lang or DEFAULT_TRANSLATE_TARGET

        job_uuid = uuid.uuid4().hex
        user_id = current_user.get("user_id", 0)
        enforce_open_jobs(user_id, locale, "translation")
        enforce_tool_burst(user_id, "translate", locale)
        enforce_quota(user_id, "translate", is_admin_user(current_user), locale)

        create_counted_job(job_uuid, user_id, "translation", filename, locale=locale)
        input_path = await asyncio.to_thread(save_queue_file_from_path, user_id, job_uuid, ext, tmp_path)
        db.set_job_input_path(job_uuid, input_path)

    from src.tasks.general_tasks import run_translate
    task = run_translate.apply_async(
        args=[job_uuid, input_path, filename, glossary, effective_source, effective_target, provider_id],
        **translate_route(zeichen, seiten),
    )
    db.set_job_celery_task_id(job_uuid, task.id)

    logger.info("Translate job {} queued for '{}'", job_uuid, filename)
    return {"job_uuid": job_uuid, "status": "pending"}
