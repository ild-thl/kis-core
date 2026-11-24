"""The demo delivers slides, the video, its audio and a comparison per voice service from prepared files."""

import base64
import io
import json
import zipfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

STIMMEN = [
    {"id": "lokal", "anbieter": "Lokal", "eigen": True, "vergleich": ["en"],
     "sprachen": {"de": {"name": "Thorsten", "stimme": "thorsten"}, "en": {"name": "Michael", "stimme": "am_michael"}}},
    {"id": "gemini", "anbieter": "Gemini", "eigen": False,
     "sprachen": {"de": {"name": "Charon"}, "en": {"name": "Charon"}}},
]


def _sprache(wurzel, sprache: str, videos: list[str]):
    ordner = wurzel / sprache
    (ordner / "folien").mkdir(parents=True)
    (ordner / "accepted_scripts.json").write_text(json.dumps([f"Eins {sprache}", f"Zwei {sprache}"]), encoding="utf-8")
    (ordner / "folientexte.json").write_text(json.dumps([f"Titel {sprache}", f"Punkte {sprache}"]), encoding="utf-8")
    (ordner / "Projektstart.pptx").write_bytes(f"PK-{sprache}".encode())
    (ordner / "ton").mkdir()
    for i in range(2):
        (ordner / "folien" / f"folie_{i:03d}.png").write_bytes(f"bild{i}{sprache}".encode())
        (ordner / "ton" / f"folie_{i:03d}.mp3").write_bytes(f"ID3{sprache}{i}".encode())
    (ordner / "video.mp4").write_bytes(f"video{sprache}-".encode() + b"0123456789" * 10)
    (ordner / "vergleich").mkdir()
    for kennung in videos:
        (ordner / "vergleich" / f"{kennung}.mp4").write_bytes(f"{kennung}{sprache}".encode())


@pytest.fixture
def demo_dir(tmp_path):
    (tmp_path / "stimmen.json").write_text(json.dumps(STIMMEN), encoding="utf-8")
    _sprache(tmp_path, "de", ["lokal", "gemini"])
    _sprache(tmp_path, "en", ["lokal"])
    with patch("src.routes.screencast_demo.DEMO_DIR", tmp_path):
        yield tmp_path


@pytest.fixture
def client(demo_dir):
    from src.dependencies import get_current_user
    from src.dependencies_rbac import get_user_permissions
    from src.permissions import resolve_user_permissions
    from src.security.auth import verify_auth
    from src.app import app

    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "email": "a@b.de", "role": "user"}
    app.dependency_overrides[get_user_permissions] = lambda: resolve_user_permissions("admin", None, True)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_folien_und_texte_je_sprache(client):
    de = client.post("/screencast-demo/translate", json={}).json()
    en = client.post("/screencast-demo/translate?sprache=en", json={}).json()
    assert [base64.b64decode(b) for b in de["slide_images"]] == [b"bild0de", b"bild1de"]
    assert de["slide_texts"] == ["Titel de", "Punkte de"]
    assert en["slide_texts"] == ["Titel en", "Punkte en"]


def test_skripte_je_sprache(client):
    assert client.post("/screencast-demo/generate-scripts?sprache=en").json()["scripts"] == ["Eins en", "Zwei en"]


def test_unbekannte_sprache_nimmt_die_standardsprache(client):
    assert client.post("/screencast-demo/translate?sprache=fr", json={}).json()["slide_texts"] == ["Titel de", "Punkte de"]
    assert client.post("/screencast-demo/translate?sprache=../en", json={}).json()["slide_texts"] == ["Titel de", "Punkte de"]


def test_stimmen_in_ihrer_reihenfolge_mit_vorhandenen_videos(client):
    stimmen = client.get("/screencast-demo/stimmen").json()["stimmen"]
    assert [s["id"] for s in stimmen] == ["lokal", "gemini"]
    assert stimmen[0] == {"id": "lokal", "anbieter": "Lokal", "eigen": True,
                          "stimmen": {"de": "Thorsten", "en": "Michael"},
                          "kennungen": {"de": "thorsten", "en": "am_michael"}, "vergleich": ["en"],
                          "videos": ["de", "en"]}
    assert stimmen[1]["videos"] == ["de"]
    assert stimmen[1]["vergleich"] == ["de", "en"]


def test_vergleich_je_sprache_und_anbieter(client):
    assert client.get("/screencast-demo/vergleich/de/gemini").content == b"geminide"
    assert client.get("/screencast-demo/vergleich/en/lokal").content == b"lokalen"


def test_fehlender_vergleich_gibt_404(client):
    assert client.get("/screencast-demo/vergleich/en/gemini").status_code == 404
    assert client.get("/screencast-demo/vergleich/de/fremd").status_code == 404
    assert client.get("/screencast-demo/vergleich/..%2Fde/lokal").status_code == 404


def test_video_je_sprache(client):
    assert client.get("/screencast-demo/video?sprache=en").content.startswith(b"videoen-")
    assert client.get("/screencast-demo/video?sprache=fr").content.startswith(b"videode-")


def test_video_laesst_sich_spulen(client):
    r = client.get("/screencast-demo/video", headers={"Range": "bytes=8-17"})
    assert r.status_code == 206
    assert r.content == b"0123456789"
    assert "attachment" not in r.headers.get("content-disposition", "")


def test_video_zum_herunterladen(client):
    r = client.get("/screencast-demo/video?download=true")
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment")
    assert "screencast_demo.mp4" in r.headers["content-disposition"]


def test_ton_je_folie(client):
    r = client.get("/screencast-demo/vorschau/1?sprache=en")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3en1"


def test_ton_ausserhalb_der_folien_gibt_404(client):
    assert client.get("/screencast-demo/vorschau/2").status_code == 404
    assert client.get("/screencast-demo/vorschau/-1").status_code == 404


def test_praesentation_je_sprache(client):
    r = client.get("/screencast-demo/pptx?sprache=en")
    assert r.status_code == 200
    assert r.content == b"PK-en"
    assert "Projektstart.pptx" in r.headers["content-disposition"]


def test_buendel_mit_video_skripten_und_praesentation(client):
    r = client.get("/screencast-demo/bundle?sprache=en")
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert set(zf.namelist()) >= {"screencast.mp4", "accepted_scripts.json", "Projektstart.pptx"}
        assert zf.read("screencast.mp4").startswith(b"videoen-")


def test_ohne_daten_meldet_die_demo_nichts_verfuegbar(client, demo_dir):
    with patch("src.routes.screencast_demo.DEMO_DIR", demo_dir / "fehlt"):
        assert client.get("/screencast-demo/available").json()["available"] is False
        assert client.get("/screencast-demo/stimmen").json()["stimmen"] == []


def test_angaben_nennen_die_stimme_des_videos(client):
    de = client.get("/screencast-demo/angaben").json()
    en = client.get("/screencast-demo/angaben?sprache=en").json()

    assert de["angaben"] == {"anbieter": "Lokal", "sprache": "de", "stimme": "Thorsten"}
    assert en["angaben"]["stimme"] == "Michael"
    assert de["datei"] == "Projektstart.pptx"
    assert de["erstellt"].endswith("Z")
