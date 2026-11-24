"""Feedback from logged-in testers, the session gate covers the login check.

Anonymous by default. The sender may opt in to attach their display name, and
may attach up to MAX_FILES screenshots or PDFs.
"""
import asyncio
import os
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from src import storage
from src.dependencies import get_current_user
from src.dependencies_rbac import require_consent
from src.features.feedback import repository as repo
from src.i18n import get_locale, t
from src.utils.file_validation import validate_or_raise
from src.utils.upload_stream import stream_upload_to_path

router = APIRouter(prefix="/feedback", tags=["feedback"], dependencies=[Depends(require_consent)])

CATEGORIES = ("bug", "idea", "other")
MAX_MESSAGE_CHARS = 2000
MAX_CONTACT_CHARS = 200
MAX_PATH_CHARS = 300
# Five screenshots of 5 MiB stay under the 32 MB proxy limit together with the form.
MAX_FILES = 5
MAX_FILE_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}


@router.post("")
async def create_feedback(
    category: str = Form(...),
    message: str = Form(...),
    contact: str | None = Form(None),
    include_username: bool = Form(False),
    page_path: str | None = Form(None),
    files: list[UploadFile] = File(default_factory=list),
    user: dict = Depends(get_current_user),
    locale: str = Depends(get_locale),
):
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=t("feedback.categoryInvalid", locale))

    message = message.strip()
    if not message:
        raise HTTPException(status_code=400, detail=t("feedback.messageRequired", locale))
    if len(message) > MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=400, detail=t("feedback.messageTooLong", locale, max=MAX_MESSAGE_CHARS)
        )

    files = [f for f in files if f.filename]
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=t("feedback.tooManyFiles", locale, max=MAX_FILES))

    username = None
    if include_username:
        username = (user.get("username") or user.get("display_name") or "").strip() or None

    with tempfile.TemporaryDirectory(prefix="feedback_upload_") as tmpdir:
        staged: list[tuple[str, str, str, str, int]] = []
        for upload in files:
            ext = os.path.splitext(upload.filename or "")[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=t(
                        "feedback.fileTypeNotAllowed", locale,
                        extensions=", ".join(sorted(ALLOWED_EXTENSIONS)),
                    ),
                )
            raw_path = os.path.join(tmpdir, f"{uuid.uuid4().hex}{ext}")
            total, head = await stream_upload_to_path(upload, raw_path, MAX_FILE_BYTES, locale)
            validate_or_raise(head, ext, locale)
            content_type = upload.content_type or "application/octet-stream"
            staged.append((raw_path, ext, (upload.filename or "")[:200], content_type, total))

        feedback_id = repo.create_feedback(
            category=category,
            message=message,
            contact=(contact or "").strip()[:MAX_CONTACT_CHARS] or None,
            username=username,
            page_path=(page_path or "").strip()[:MAX_PATH_CHARS] or None,
        )

        for raw_path, ext, filename, content_type, size in staged:
            attachment_uuid = uuid.uuid4().hex
            storage_key = await asyncio.to_thread(
                storage.save_feedback_attachment_from_path,
                feedback_id, attachment_uuid, ext, raw_path,
            )
            repo.add_attachment(
                feedback_id=feedback_id,
                filename=filename,
                content_type=content_type,
                size_bytes=size,
                storage_key=storage_key,
            )

    return {"id": feedback_id}
