"""The admin page: check settings, accept documents, trigger the sync."""
import io

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from src.routes.admin import campus as admin_campus

ADMIN = {"user_id": 1, "role": "admin"}


@pytest.fixture
def umgebung(monkeypatch):
    gespeichert = {}
    monkeypatch.setattr(admin_campus.campus_settings, "write", lambda values: gespeichert.update(values))
    monkeypatch.setattr(admin_campus, "_overview", lambda: {"settings": gespeichert})
    monkeypatch.setattr("src.services.web_page_fetch._resolve", lambda host: ["93.184.216.34"])
    return gespeichert


def test_einstellungen_nur_mit_oeffentlicher_adresse(umgebung):
    body = admin_campus.SettingsBody(sitemap_url="https://x.test/sitemap.xml", retention_days=30)
    admin_campus.update_campus(body, admin=ADMIN, locale="de")
    assert umgebung == {"sitemap_url": "https://x.test/sitemap.xml", "retention_days": 30}
    with pytest.raises(HTTPException) as info:
        admin_campus.update_campus(admin_campus.SettingsBody(sitemap_url="http://localhost/sitemap.xml"), admin=ADMIN, locale="de")
    assert info.value.status_code == 400


async def test_dokument_falscher_typ_und_doppelt(monkeypatch):
    monkeypatch.setattr(admin_campus.page_repo, "list_pages", lambda kind: [{"filename": "ordnung.pdf"}])
    with pytest.raises(HTTPException) as info:
        await admin_campus.upload_document(UploadFile(io.BytesIO(b"x"), filename="bild.png"), admin=ADMIN, locale="de")
    assert info.value.status_code == 400
    with pytest.raises(HTTPException) as info:
        await admin_campus.upload_document(UploadFile(io.BytesIO(b"%PDF-1.4"), filename="ordnung.pdf"), admin=ADMIN, locale="de")
    assert info.value.status_code == 409


async def test_dokument_wird_gespeichert_und_eingereiht(monkeypatch):
    monkeypatch.setattr(admin_campus.page_repo, "list_pages", lambda kind: [])
    monkeypatch.setattr(admin_campus.storage, "save_key_file", lambda key, data: f"/store/{key}")
    angelegt = {}

    def upsert(kind, url, title=None, filename=None, file_path=None):
        angelegt.update(kind=kind, title=title, filename=filename, file_path=file_path)
        return 5

    monkeypatch.setattr(admin_campus.page_repo, "upsert_page", upsert)
    monkeypatch.setattr(admin_campus.page_repo, "get_page", lambda pid: {"id": pid, "filename": "faq.md", "title": "faq", "status": "pending", "chunk_count": 0, "error_message": None, "created_at": None})
    eingereiht = []
    import src.features.campus.tasks as tasks
    monkeypatch.setattr(tasks.run_index_document, "delay", lambda pid: eingereiht.append(pid))
    out = await admin_campus.upload_document(UploadFile(io.BytesIO("# FAQ\n\nText".encode()), filename="faq.md"), admin=ADMIN, locale="de")
    assert out["id"] == 5 and eingereiht == [5]
    assert angelegt["kind"] == "document" and angelegt["file_path"].startswith("/store/campus/documents/") and angelegt["title"] == "faq"


def test_abgleich_wird_eingereiht(monkeypatch):
    from src.features.campus.services.settings import CampusSettings
    monkeypatch.setattr(admin_campus.campus_settings, "read", lambda: CampusSettings(sitemap_url="https://x.test/sitemap.xml"))
    monkeypatch.setattr(admin_campus.campus_settings, "crawl_status", lambda: {})
    gesetzt = {}
    monkeypatch.setattr(admin_campus.campus_settings, "set_crawl_status", lambda s: gesetzt.update(s))
    import src.features.campus.tasks as tasks
    aufgerufen = []
    monkeypatch.setattr(tasks.run_crawl, "delay", lambda: aufgerufen.append(True))
    out = admin_campus.start_crawl(admin=ADMIN)
    assert out["running"] and aufgerufen == [True] and gesetzt["queued"]


def test_mehrere_sitemap_adressen_je_zeile_werden_geprueft(umgebung):
    admin_campus.update_campus(admin_campus.SettingsBody(sitemap_url="https://x.test/a.xml\nhttps://y.test/b.xml"), admin=ADMIN, locale="de")
    with pytest.raises(HTTPException):
        admin_campus.update_campus(admin_campus.SettingsBody(sitemap_url="https://x.test/a.xml\nhttp://localhost/b.xml"), admin=ADMIN, locale="de")


def test_seite_ausschliessen_entfernt_sie_und_merkt_die_adresse(monkeypatch):
    monkeypatch.setattr("src.services.web_page_fetch._resolve", lambda host: ["93.184.216.34"])
    gemerkt, geloescht = [], []
    monkeypatch.setattr(admin_campus.excluded_repo, "add", gemerkt.append)
    monkeypatch.setattr(admin_campus.page_repo, "get_page_by_url", lambda url: {"id": 5, "kind": "page"})
    monkeypatch.setattr(admin_campus.page_repo, "delete_page", geloescht.append)
    admin_campus.exclude_page(admin_campus.ExcludeBody(url=" https://x.test/a/ "), admin=ADMIN, locale="de")
    assert gemerkt == ["https://x.test/a/"] and geloescht == [5]
    with pytest.raises(HTTPException):
        admin_campus.exclude_page(admin_campus.ExcludeBody(url="javascript:alert(1)"), admin=ADMIN, locale="de")


def test_naechtlicher_abgleich_kommt_aus_dem_zeitplan(monkeypatch):
    from celery.schedules import crontab
    monkeypatch.setitem(admin_campus.celery_app.conf.beat_schedule, "campus-crawl", {"schedule": crontab(hour=2, minute=5)})
    assert admin_campus._nightly_crawl() == {"hour_utc": 2, "minute_utc": 5}
    monkeypatch.setitem(admin_campus.celery_app.conf.beat_schedule, "campus-crawl", {"schedule": 3600.0})
    assert admin_campus._nightly_crawl() is None
