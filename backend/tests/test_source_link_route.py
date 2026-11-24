"""One link becomes one PDF source, every rejection comes back before a row exists."""
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.features.ai_assistant.routes.sources import _link, _upload
from src.services.web_page_fetch import FetchedPage, LinkError

WS = {"id": 7, "uuid": "w1", "user_id": 42}
_ABSATZ = ("Die Photosynthese ist ein biochemischer Prozess, bei dem Pflanzen Lichtenergie "
           "in chemische Energie umwandeln und dabei Zucker und Sauerstoff herstellen. ")
# A running prefix keeps every paragraph unique, trafilatura 2.2 drops byte-identical ones over 50 chars.
_HTML = ("<html><head><title>Photosynthese</title></head><body><main><article><h1>Photosynthese</h1>"
         + "".join(f"<p>Absatz {i + 1}: {_ABSATZ}</p>" for i in range(6)) + "</article></main></body></html>").encode("utf-8")


@pytest.fixture
def route(monkeypatch):
    """Everything around the route stubbed, the calls recorded."""
    calls = {"existing": []}
    monkeypatch.setattr(_link, "_require_workspace_manage", lambda *a, **k: WS)
    monkeypatch.setattr(_link, "check_upload_limit", lambda *a, **k: None)
    monkeypatch.setattr(_link, "record_upload", lambda uid: calls.setdefault("recorded", []).append(uid))
    monkeypatch.setattr(_link.db, "get_aia_sources_by_workspace", lambda wid: calls["existing"])
    monkeypatch.setattr(_link, "_require_source_capacity", lambda *a, **k: None)
    monkeypatch.setattr(_link, "_workspace_label", lambda locale: "Modul")
    monkeypatch.setattr(_upload, "_claim_upload_slot", lambda limit: "ticket")
    monkeypatch.setattr(_upload, "_release_upload_slot", lambda ticket: calls.setdefault("released", []).append(ticket))
    monkeypatch.setattr(_link, "validate_url", lambda raw: raw.strip())

    async def _register(workspace, workspace_uuid, final_path, ext, filename, uid, locale, source_url=None):
        calls["registered"] = {
            "ext": ext, "filename": filename, "source_url": source_url,
            "bytes": Path(final_path).read_bytes(),
        }
        return {"uuid": "neu", "filename": filename, "status": "pending", "source_url": source_url}

    monkeypatch.setattr(_link, "_register_source_file", _register)

    def _convert(src, ext, out_dir, locale):
        calls["converted_html"] = Path(src).read_text(encoding="utf-8")
        out = Path(out_dir) / "page.pdf"
        out.write_bytes(b"%PDF-1.4 fake")
        return str(out)

    monkeypatch.setattr(_link, "_convert_office_to_pdf_path", _convert)
    return calls


def _seite(kind, body, url="https://example.org/artikel"):
    return FetchedPage(kind=kind, body=body, final_url=url, content_type="")


async def _aufruf(url):
    return await _link.add_link_source(
        workspace_uuid="w1", body=_link.LinkBody(url=url),
        current_user={"user_id": 42}, locale="de",
    )


@pytest.mark.asyncio
async def test_html_seite_wird_pdf(route, monkeypatch):
    monkeypatch.setattr(_link, "fetch_page", lambda url: _seite("html", _HTML))

    antwort = await _aufruf("https://example.org/artikel")

    assert antwort["uuid"] == "neu"
    assert route["registered"]["ext"] == ".pdf"
    assert route["registered"]["filename"] == "Photosynthese.pdf"
    assert route["registered"]["source_url"] == "https://example.org/artikel"
    assert route["registered"]["bytes"].startswith(b"%PDF")
    assert "Quelle: https://example.org/artikel, abgerufen am" in route["converted_html"]
    assert "<h1>Photosynthese</h1>" in route["converted_html"]
    assert route["recorded"] == [42]
    assert route["released"] == ["ticket"]


@pytest.mark.asyncio
async def test_pdf_link_geht_ohne_umweg(route, monkeypatch):
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF"
    monkeypatch.setattr(_link, "fetch_page", lambda url: _seite("pdf", pdf, url="https://example.org/lehre/Skript%20WS.pdf"))

    await _aufruf("https://example.org/lehre/Skript%20WS.pdf")

    assert "converted_html" not in route
    assert route["registered"]["bytes"] == pdf
    assert route["registered"]["filename"] == "Skript WS.pdf"


@pytest.mark.asyncio
async def test_textseite_wird_pdf(route, monkeypatch):
    text = (("Nur Text. " * 150) + "\n\n" + ("Noch mehr Text. " * 20)).encode("utf-8")
    monkeypatch.setattr(_link, "fetch_page", lambda url: _seite("text", text, url="https://example.org/notizen.txt"))

    await _aufruf("https://example.org/notizen.txt")

    assert route["registered"]["filename"] == "example.org notizen.txt.pdf"
    assert route["converted_html"].count("<p>") == 3


@pytest.mark.asyncio
async def test_doppelter_link_gibt_409(route, monkeypatch):
    route["existing"] = [{"filename": "x.pdf", "source_url": "https://example.org/artikel/"}]
    monkeypatch.setattr(_link, "fetch_page", lambda url: pytest.fail("darf nicht holen"))

    with pytest.raises(HTTPException) as exc:
        await _aufruf("https://Example.org/artikel#oben")

    assert exc.value.status_code == 409
    assert exc.value.detail == "Dieser Link ist schon im Modul."
    assert "recorded" not in route


@pytest.mark.asyncio
async def test_namenskollision_haengt_eine_zahl_an(route, monkeypatch):
    route["existing"] = [
        {"filename": "Photosynthese.pdf", "source_url": None},
        {"filename": "photosynthese (2).pdf", "source_url": None},
    ]
    monkeypatch.setattr(_link, "fetch_page", lambda url: _seite("html", _HTML))

    await _aufruf("https://example.org/artikel")

    assert route["registered"]["filename"] == "Photosynthese (3).pdf"


@pytest.mark.asyncio
async def test_gesperrter_link_gibt_den_text_und_zaehlt_nicht(route, monkeypatch):
    def _sperre(url):
        raise LinkError("ai.link.forbiddenAddress", 400)

    monkeypatch.setattr(_link, "fetch_page", _sperre)

    with pytest.raises(HTTPException) as exc:
        await _aufruf("http://10.0.0.5/")

    assert exc.value.status_code == 400
    assert exc.value.detail == "Diese Adresse darf nicht abgerufen werden."
    assert "recorded" not in route
    assert route["released"] == ["ticket"]


@pytest.mark.asyncio
async def test_serverfehler_traegt_den_status_im_text(route, monkeypatch):
    def _kaputt(url):
        raise LinkError("ai.link.httpError", 502, status=503)

    monkeypatch.setattr(_link, "fetch_page", _kaputt)

    with pytest.raises(HTTPException) as exc:
        await _aufruf("https://example.org/")

    assert exc.value.status_code == 502
    assert exc.value.detail == "Die Seite antwortet mit Fehler 503."


@pytest.mark.asyncio
async def test_ungueltiger_link_faellt_vor_der_bremse(route, monkeypatch):
    def _ungueltig(raw):
        raise LinkError("ai.link.invalid", 400)

    monkeypatch.setattr(_link, "validate_url", _ungueltig)
    monkeypatch.setattr(_upload, "_claim_upload_slot", lambda limit: pytest.fail("Bremse darf nicht greifen"))

    with pytest.raises(HTTPException) as exc:
        await _aufruf("hallo")

    assert exc.value.status_code == 400
    assert exc.value.detail == "Das ist kein gültiger Link."


@pytest.mark.asyncio
async def test_ohne_recht_kommt_403_und_nichts_passiert(route, monkeypatch):
    def _verboten(*a, **k):
        raise HTTPException(status_code=403, detail="nein")

    monkeypatch.setattr(_link, "_require_workspace_manage", _verboten)
    monkeypatch.setattr(_link, "fetch_page", lambda url: pytest.fail("darf nicht holen"))

    with pytest.raises(HTTPException) as exc:
        await _aufruf("https://example.org/")

    assert exc.value.status_code == 403
    assert "recorded" not in route


@pytest.mark.asyncio
async def test_kein_platz_gibt_503(route, monkeypatch):
    monkeypatch.setattr(_upload, "_claim_upload_slot", lambda limit: None)
    # The route waits a while for a slot first, the test skips the wait.
    monkeypatch.setattr(_upload, "_UPLOAD_SLOT_WAIT_SECONDS", 0)

    with pytest.raises(HTTPException) as exc:
        await _aufruf("https://example.org/")

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_youtube_link_wird_mit_hinweis_abgewiesen(route, monkeypatch):
    monkeypatch.setattr(_link, "fetch_page", lambda url: pytest.fail("darf nicht holen"))

    with pytest.raises(HTTPException) as exc:
        await _aufruf("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert exc.value.status_code == 400
    assert exc.value.detail == "Das ist ein YouTube-Link. Nutze dafür den Abschnitt YouTube-Video."
    assert "recorded" not in route


@pytest.mark.asyncio
async def test_pages_link_wird_seite(route, monkeypatch):
    monkeypatch.setattr(_link.pages_repo, "page_by_code", lambda code: {"job_uuid": "j1", "user_id": 42})
    gerufen = {}

    async def _seite_dazu(workspace_uuid, body, current_user, locale):
        gerufen["job"] = body.job_uuid
        return {"uuid": "neu", "filename": "Seite.page", "status": "pending", "source_url": "pages:j1"}

    monkeypatch.setattr(_link._page, "add_page_source", _seite_dazu)
    monkeypatch.setattr(_link, "fetch_page", lambda url: pytest.fail("kein Abruf"))

    antwort = await _aufruf("https://askfrancis.example/en/p/abcdefghjkmnpqrs")

    assert gerufen["job"] == "j1"
    assert antwort["source_url"] == "pages:j1"


@pytest.mark.asyncio
async def test_fremde_seite_wird_abgelehnt(route, monkeypatch):
    monkeypatch.setattr(_link.pages_repo, "page_by_code", lambda code: {"job_uuid": "j1", "user_id": 99})

    with pytest.raises(HTTPException) as e:
        await _aufruf("https://askfrancis.example/p/abcdefghjkmnpqrs")

    assert e.value.status_code == 403
    assert "recorded" not in route


def test_nur_seitenpfade_zaehlen(monkeypatch):
    monkeypatch.setattr(_link.pages_repo, "page_by_code", lambda code: {"job_uuid": code, "user_id": 1})
    monkeypatch.setattr(_link.db, "get_job", lambda uuid: {"job_uuid": uuid, "user_id": 1, "tool": "pages"})

    assert _link._page_of_link("https://askfrancis.example/p/abcdefghjkmnpqrs")["job_uuid"] == "abcdefghjkmnpqrs"
    assert _link._page_of_link("https://askfrancis.example/de/tools/pages/" + "a" * 32)["job_uuid"] == "a" * 32
    assert _link._page_of_link("https://example.org/p/kurz") is None
    assert _link._page_of_link("https://example.org/artikel") is None
