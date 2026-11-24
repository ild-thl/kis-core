"""The summary and presentation demos deliver prepared results from files."""

import io
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image


def _png() -> bytes:
    aus = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(aus, "PNG")
    return aus.getvalue()


def _folie(sid: str, bilder: int) -> dict:
    return {"id": sid, "role": "text", "layout": 1, "title": sid, "subtitle": "", "body": None,
            "columns": [], "images": [{"prompt": "p"}] * bilder, "notes": ""}


@pytest.fixture
def zusammenfassung(tmp_path):
    (tmp_path / "demo.json").write_text(json.dumps({
        "workspace": "Projektmanagement", "dateien": ["A.pdf", "B.pdf"], "anweisung": "Kurz halten",
        "anbieter": "Lokal", "erstellt": "2026-10-01T01:38:17Z",
    }), encoding="utf-8")
    (tmp_path / "kurzbriefing").mkdir()
    (tmp_path / "kurzbriefing" / "Kurzbriefing.md").write_text("# T\n\n## Eins\n\nx\n\n### Zwei\n\ny\n", encoding="utf-8")
    (tmp_path / "kurzbriefing" / "Kurzbriefing.docx").write_bytes(b"PK-docx")
    # A folder without its Markdown counts as not prepared.
    (tmp_path / "zeitstrahl").mkdir()
    with patch("src.routes.summary_demo.DEMO_DIR", tmp_path):
        yield tmp_path


@pytest.fixture
def praesentation(tmp_path):
    (tmp_path / "ansicht.json").write_text(json.dumps({
        "params": {"language": "de", "notes": True, "notes_include": True, "template_id": "thl"},
        "outline": {"title": "Der Projektstart!", "subtitle": "", "rows": []},
        "slides": [_folie("s1", 1), _folie("s2", 1)],
        "workspace": "Projektmanagement", "dateien": ["Skript.pdf"],
        "angaben": {"anbieter": "Lokal", "bildanbieter": "Lokal Bild"}, "erstellt": "2026-10-01T09:57:28Z",
    }), encoding="utf-8")
    (tmp_path / "preview").mkdir()
    (tmp_path / "images").mkdir()
    for sid in ("s1", "s2"):
        (tmp_path / "preview" / f"{sid}.png").write_bytes(_png())
    (tmp_path / "images" / "s1_0.png").write_bytes(_png())
    (tmp_path / "deck.pptx").write_bytes(b"PK-pptx")
    with patch("src.routes.praesentation_demo.DEMO_DIR", tmp_path):
        yield tmp_path


@pytest.fixture
def podcast(tmp_path_factory):
    ordner = tmp_path_factory.mktemp("podcast")
    (ordner / "ansicht.json").write_text(json.dumps({
        "params": {"persons": [{"name": "Lena"}, {"name": "Jonas"}]},
        "lines": [{"id": "b0", "speaker": 0, "text": "Hallo"}, {"id": "b1", "speaker": 1, "text": "Servus"}],
        "seconds": 12.5, "workspace": "Projektmanagement", "dateien": ["Skript.pdf"],
        "angaben": {"anbieter": "Lokal", "besetzung": [{"name": "Lena", "rolle": "host", "stimme": "Kerstin"}]},
        "erstellt": "2026-10-01T12:39:06Z",
    }), encoding="utf-8")
    (ordner / "audio").mkdir()
    (ordner / "audio" / "b0.mp3").write_bytes(b"ID3eins")
    (ordner / "podcast.mp3").write_bytes(b"ID3ganz")
    (ordner / "vergleich").mkdir()
    (ordner / "vergleich" / "vergleich.json").write_text(json.dumps([
        {"id": "gemini", "sprache": "de", "anbieter": "Gemini", "stimmen": ["Aoede", "Charon"]},
        {"id": "fish", "sprache": "de", "anbieter": "Fish Audio", "stimmen": ["Sabine", "Ben"]},
        {"id": "fish-en", "sprache": "en", "anbieter": "Fish Audio", "stimmen": ["Laura", "Ethan"]},
    ]), encoding="utf-8")
    (ordner / "vergleich" / "gemini.mp3").write_bytes(b"ID3gemini")
    (ordner / "vergleich" / "fish-en.mp3").write_bytes(b"ID3fishen")
    with patch("src.routes.podcast_demo.DEMO_DIR", ordner), \
         patch("src.routes.podcast_demo.VERGLEICH_DIR", ordner / "vergleich"):
        yield ordner


@pytest.fixture
def client(zusammenfassung, praesentation, podcast):
    from src.app import app
    from src.dependencies import get_current_user
    from src.dependencies_rbac import get_user_permissions
    from src.permissions import resolve_user_permissions
    from src.security.auth import verify_auth

    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "email": "a@b.de", "role": "user"}
    app.dependency_overrides[get_user_permissions] = lambda: resolve_user_permissions("admin", None, True)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_zusammenfassung_nennt_material_und_vorbereitete_vorlagen(client):
    r = client.get("/summary-demo/setup")
    assert r.status_code == 200
    assert r.json() == {
        "workspace": "Projektmanagement", "files": ["A.pdf", "B.pdf"], "instructions": "Kurz halten",
        "provider": "Lokal", "created": "2026-10-01T01:38:17Z",
        "templates": ["kurzbriefing"], "sections": {"kurzbriefing": 2},
    }


def test_zusammenfassung_als_markdown_und_word(client):
    md = client.get("/summary-demo/kurzbriefing/md")
    assert md.status_code == 200
    assert md.content.startswith(b"\xef\xbb\xbf# T")
    docx = client.get("/summary-demo/kurzbriefing/docx")
    assert docx.content == b"PK-docx"
    assert "Kurzbriefing.docx" in docx.headers["content-disposition"]


def test_zusammenfassung_ohne_ergebnis_oder_fremder_name_gibt_404(client):
    assert client.get("/summary-demo/zeitstrahl/md").status_code == 404
    assert client.get("/summary-demo/kurzbriefing/pdf").status_code == 404
    assert client.get("/summary-demo/..%2F..%2Fetc/md").status_code == 404


def test_praesentation_ansicht_wie_ein_fertiger_lauf(client):
    r = client.get("/praesentation-demo/ansicht")
    assert r.status_code == 200
    v = r.json()
    assert v["status"] == "success"
    assert v["previews"] == ["s1", "s2"]
    assert v["images"] == {"s1": ["0"], "s2": []}
    assert v["missing_images"] == ["s2"]
    assert v["has_deck"] is True
    assert v["files"] == ["Skript.pdf"]
    assert v["angaben"] == {"anbieter": "Lokal", "bildanbieter": "Lokal Bild", "vorlage": "thl", "sprache": "de"}
    assert v["erstellt"] == "2026-10-01T09:57:28Z"
    assert client.get("/praesentation-demo/available").json() == {"available": True}


def test_praesentation_bilder_und_datei(client):
    assert client.get("/praesentation-demo/preview/s1.png").headers["content-type"] == "image/png"
    assert client.get("/praesentation-demo/image/s1/0").status_code == 200
    assert client.get("/praesentation-demo/image/s2/0").status_code == 404
    assert client.get("/praesentation-demo/preview/x1.png").status_code == 404
    deck = client.get("/praesentation-demo/download")
    assert deck.content == b"PK-pptx"
    assert "Der Projektstart.pptx" in deck.headers["content-disposition"]


def test_praesentation_ohne_vorbereiteten_lauf(client, praesentation):
    (praesentation / "ansicht.json").unlink()
    assert client.get("/praesentation-demo/available").json() == {"available": False}
    assert client.get("/praesentation-demo/ansicht").status_code == 404


def test_podcast_ansicht_wie_ein_fertiger_lauf(client):
    v = client.get("/podcast-demo/ansicht").json()
    assert v["status"] == "success"
    assert v["voiced"] == ["b0"]
    assert v["seconds"] == 12.5
    assert v["files"] == ["Skript.pdf"]
    assert v["angaben"]["besetzung"] == [{"name": "Lena", "rolle": "host", "stimme": "Kerstin"}]
    assert v["erstellt"] == "2026-10-01T12:39:06Z"
    assert client.get("/podcast-demo/available").json() == {"available": True}


def test_podcast_ton_datei_und_transkript(client):
    assert client.get("/podcast-demo/line/b0").content == b"ID3eins"
    assert client.get("/podcast-demo/line/b1").status_code == 404
    assert client.get("/podcast-demo/line/x").status_code == 404
    assert client.get("/podcast-demo/download").content == b"ID3ganz"
    assert client.get("/podcast-demo/transcript").content == b"\xef\xbb\xbfLena: Hallo\n\nJonas: Servus\n"


def test_podcast_vergleich_ohne_datei_als_platzhalter(client):
    v = client.get("/podcast-demo/ansicht").json()
    assert v["vergleich"] == [
        {"id": "gemini", "sprache": "de", "anbieter": "Gemini", "stimmen": ["Aoede", "Charon"], "ton": True},
        {"id": "fish", "sprache": "de", "anbieter": "Fish Audio", "stimmen": ["Sabine", "Ben"], "ton": False},
        {"id": "fish-en", "sprache": "en", "anbieter": "Fish Audio", "stimmen": ["Laura", "Ethan"], "ton": True},
    ]
    assert client.get("/podcast-demo/vergleich/gemini").content == b"ID3gemini"
    assert client.get("/podcast-demo/vergleich/fish-en").content == b"ID3fishen"
    assert client.get("/podcast-demo/vergleich/fish").status_code == 404
    assert client.get("/podcast-demo/vergleich/..").status_code == 404
