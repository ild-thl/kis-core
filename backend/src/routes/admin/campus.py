"""Settings, crawl status and documents of the campus assistant."""
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from src import storage
from src.celery_app import celery_app
from src.dependencies_rbac import require_permission
from src.features.campus.repository import excluded as excluded_repo
from src.features.campus.repository import pages as page_repo
from src.features.campus.services import fetch as fetch_mod
from src.features.campus.services import settings as campus_settings
from src.features.campus.services import sitemap as sitemap_mod
from src.i18n import get_locale, t
from src.limits import CAMPUS_CRAWL_MAX_PAGES, CAMPUS_PAGE_MAX_CHUNKS
from src.permissions_registry import PERM_SET_CAMPUS
from src.services import tool_limits
from src.utils.file_validation import validate_or_raise

router = APIRouter(prefix="/campus", tags=["admin: campus"])

_require = require_permission(PERM_SET_CAMPUS)
_DOC_EXTENSIONS = (".pdf", ".docx", ".pptx", ".md", ".txt")

# Large documents go in parts straight into the bucket, only someone with the campus permission may send them.
from src.routes.uploads import permission_access  # noqa: E402
from src.services import direct_upload  # noqa: E402

direct_upload.register("campus", direct_upload.UploadRule(
    _DOC_EXTENSIONS, lambda: tool_limits.max_upload_bytes(), permission_access(PERM_SET_CAMPUS)))
_PAGE_STATUSES = ("pending", "ready", "failed")


class ExcludeBody(BaseModel):
    url: str


class SettingsBody(BaseModel):
    sitemap_url: Optional[str] = None
    start_urls: Optional[str] = None
    url_include: Optional[str] = None
    url_exclude: Optional[str] = None
    retention_days: Optional[int] = None


def _nightly_crawl() -> dict | None:
    """Hour and minute of the nightly refresh in UTC, straight from the beat schedule."""
    entry = celery_app.conf.beat_schedule.get("campus-crawl")
    sched = entry and entry.get("schedule")
    if not hasattr(sched, "hour") or not hasattr(sched, "minute"):
        return None
    return {"hour_utc": min(sched.hour), "minute_utc": min(sched.minute)}


def _overview() -> dict:
    cfg = campus_settings.read()
    return {
        "settings": cfg.as_dict(),
        "status": campus_settings.crawl_status(),
        "stats": page_repo.page_stats(),
        "nightly": _nightly_crawl(),
        "limits": {"max_pages": CAMPUS_CRAWL_MAX_PAGES, "max_chunks_per_page": CAMPUS_PAGE_MAX_CHUNKS},
        "documents": [_document(d) for d in page_repo.list_pages(page_repo.KIND_DOCUMENT)],
    }


def _document(page: dict) -> dict:
    return {
        "id": page["id"], "filename": page["filename"], "title": page["title"], "status": page["status"],
        "chunk_count": page["chunk_count"], "error_message": page["error_message"],
        "created_at": page["created_at"].isoformat() if page.get("created_at") else None,
    }


@router.get("")
def get_campus(admin: dict = Depends(_require)):
    return _overview()


@router.get("/pages")
def list_pages(
    q: str = Query("", max_length=200),
    status: str = Query("", max_length=20),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(_require),
):
    rows, total = page_repo.search_pages(q.strip(), status if status in _PAGE_STATUSES else "", limit, offset)
    items = [
        {
            "id": r["id"], "url": r["url"], "title": r["title"], "status": r["status"], "chunk_count": r["chunk_count"],
            "error_message": r["error_message"], "fetched_at": r["fetched_at"].isoformat() if r.get("fetched_at") else None,
        }
        for r in rows
    ]
    return {"items": items, "total": total, "excluded": excluded_repo.list_all()}


@router.post("/pages/exclude")
def exclude_page(body: ExcludeBody, admin: dict = Depends(_require), locale: str = Depends(get_locale)):
    """Takes a page out of the index now and keeps the crawl from bringing it back."""
    url = body.url.strip()
    if not url or not fetch_mod.is_web_url(url):
        raise HTTPException(status_code=400, detail=t("campus.urlInvalid", locale))
    excluded_repo.add(url)
    page = page_repo.get_page_by_url(url)
    if page is not None and page["kind"] == page_repo.KIND_PAGE:
        page_repo.delete_page(page["id"])
    return {"excluded": True}


@router.post("/pages/include")
def include_page(body: ExcludeBody, admin: dict = Depends(_require)):
    """Lets a page back in, the next crawl reads it again."""
    return {"included": excluded_repo.remove(body.url.strip())}


@router.patch("")
def update_campus(body: SettingsBody, admin: dict = Depends(_require), locale: str = Depends(get_locale)):
    values = body.model_dump(exclude_unset=True)
    urls = sitemap_mod.parse_patterns(values.get("sitemap_url") or "") + sitemap_mod.parse_patterns(values.get("start_urls") or "")
    if any(not fetch_mod.is_web_url(u) for u in urls):
        raise HTTPException(status_code=400, detail=t("campus.urlInvalid", locale))
    campus_settings.write(values)
    return _overview()


@router.post("/crawl")
def start_crawl(admin: dict = Depends(_require)):
    status = campus_settings.crawl_status()
    if status.get("running"):
        return status
    from src.features.campus.tasks import run_crawl
    run_crawl.delay()
    status = {"queued": True, "running": True}
    campus_settings.set_crawl_status(status)
    return status


@router.post("/documents")
async def upload_document(file: UploadFile | None = File(None), upload_token: str | None = Form(None),
                          admin: dict = Depends(_require), locale: str = Depends(get_locale)):
    user_id = admin.get("user_id", 0)
    filename = Path(direct_upload.input_name(file, upload_token, "campus", user_id, locale) or "").name
    ext = Path(filename).suffix.lower()
    if ext not in _DOC_EXTENSIONS:
        raise HTTPException(status_code=400, detail=t("campus.docTypeNotAllowed", locale))
    if any(d["filename"] == filename for d in page_repo.list_pages(page_repo.KIND_DOCUMENT)):
        raise HTTPException(status_code=409, detail=t("campus.docDuplicate", locale))
    limit = tool_limits.max_upload_bytes()
    key = f"campus/documents/{uuid.uuid4().hex}{ext}"
    if direct_upload.input_name(None, upload_token, "campus", user_id, locale):
        # Checked on completion already, the bucket copies it without passing through here.
        session = direct_upload.claim(upload_token, "campus", user_id, locale)
        storage.copy_key(session["key"], key)
        direct_upload.delete_file(session["key"])
        stored = key
    else:
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(status_code=413, detail=t("file.tooLargeMb", locale, max=limit // (1024 * 1024)))
        validate_or_raise(data[:8192], ext, locale)
        stored = storage.save_key_file(key, data)
    page_id = page_repo.upsert_page(page_repo.KIND_DOCUMENT, None, title=Path(filename).stem, filename=filename, file_path=stored)
    from src.features.campus.tasks import run_index_document
    run_index_document.delay(page_id)
    return _document(page_repo.get_page(page_id))


@router.delete("/documents/{page_id}")
def delete_document(page_id: int, admin: dict = Depends(_require), locale: str = Depends(get_locale)):
    page = page_repo.get_page(page_id)
    if page is None or page["kind"] != page_repo.KIND_DOCUMENT:
        raise HTTPException(status_code=404, detail=t("campus.documentNotFound", locale))
    if page.get("file_path"):
        try:
            storage.delete_file(page["file_path"])
        except Exception:
            pass
    page_repo.delete_page(page_id)
    return {"deleted": True}
