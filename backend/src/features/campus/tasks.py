"""Celery tasks of the campus assistant: the nightly crawl, document indexing and chat cleanup."""
from datetime import datetime, timezone

from loguru import logger

from src.celery_app import celery_app
from src.features.campus.repository import chats as chat_repo
from src.features.campus.repository import excluded as excluded_repo
from src.features.campus.repository import pages as page_repo
from src.features.campus.services import crawler, places_sync
from src.features.campus.services import fetch as fetch_mod
from src.features.campus.services import settings as campus_settings
from src.features.campus.services.indexer import embedder, index_markdown
from src.limits import CAMPUS_CRAWL_TIME_LIMIT_SECONDS


def _now_iso() -> str:
    """UTC without offset, the form the rest of the backend hands to the browser."""
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat()


@celery_app.task(
    name="campus.crawl", queue="long",
    soft_time_limit=CAMPUS_CRAWL_TIME_LIMIT_SECONDS, time_limit=CAMPUS_CRAWL_TIME_LIMIT_SECONDS + 300,
)
def run_crawl() -> dict:
    """Syncs the place list of the configured map and crawls the web pages when a sitemap or start address is configured."""
    cfg = campus_settings.read()
    status = {"started_at": _now_iso(), "running": True}
    campus_settings.set_crawl_status(status)
    try:
        embed = embedder()
        client = fetch_mod.make_client()
        # A broken place list must not cost the night its page crawl.
        try:
            status["places"] = places_sync.sync(places_sync.fetch_places(client, cfg.map_url), cfg.map_url, embed)
        except Exception as e:  # noqa: BLE001
            logger.exception("Campus: Ortsliste nicht eingelesen")
            status["places_error"] = f"{type(e).__name__}: {e}"[:300]
        if cfg.sitemap_url or cfg.start_urls:
            status.update(crawler.run(cfg, embed, client=client, excluded_urls=excluded_repo.list_urls()))
        status["error"] = None
    except Exception as e:
        logger.exception("Campus: Abgleich fehlgeschlagen")
        status["error"] = f"{type(e).__name__}: {e}"[:300]
    status["running"] = False
    status["finished_at"] = _now_iso()
    campus_settings.set_crawl_status(status)
    return status


@celery_app.task(name="campus.index_document", queue="long")
def run_index_document(page_id: int) -> int:
    """Extracts an uploaded document the way the assistant does and indexes its text."""
    from src.services.aia_chunker import extract_chunks
    from src.storage import open_input_file

    page = page_repo.get_page(page_id)
    if page is None or not page.get("file_path"):
        return 0
    page_repo.set_page_status(page_id, "indexing")
    try:
        file_type = (page.get("filename") or "").rsplit(".", 1)[-1].lower()
        with open_input_file(page["file_path"]) as local_path:
            pieces = extract_chunks(local_path, file_type)
        markdown = f"# {page.get('title') or page.get('filename')}\n\n" + "\n\n".join(
            f"## Seite {p['page_number']}\n\n{p['content']}" if p.get("page_number") else p["content"] for p in pieces
        )
        return index_markdown(page_id, page.get("title"), markdown, embedder(), force=True)
    except Exception as e:
        logger.exception("Campus: Dokument {} nicht indexiert", page_id)
        page_repo.set_page_status(page_id, "failed", f"{type(e).__name__}: {e}")
        return 0


@celery_app.task(name="cleanup.campus_chats", queue="general")
def run_cleanup_campus_chats() -> int:
    """Removes chats nobody touched for the configured number of days. Nightly."""
    try:
        n = chat_repo.prune_chats(campus_settings.read().retention_days)
        if n:
            logger.info("Cleanup: {} Campus-Chat(s) geloescht", n)
        return n
    except Exception as e:
        logger.warning("Cleanup Campus-Chats fehlgeschlagen: {}", e)
        return 0
