"""Feedback: anyone with a session submits anonymously, viewing needs the permission."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# Out of local mode, otherwise the app's own session middleware hits the real database.
def _out_of_local_mode(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")


@pytest.fixture
def client(monkeypatch):
    _out_of_local_mode(monkeypatch)
    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth
    from src.app import app

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 1, "email": "user@example.org", "role": "user",
        "username": "max.mustermann", "display_name": "Max Mustermann",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def admin_client(monkeypatch):
    _out_of_local_mode(monkeypatch)
    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth
    from src.app import app

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 1, "email": "admin@example.org", "role": "admin",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def client_ohne_sitzung(monkeypatch):
    _out_of_local_mode(monkeypatch)
    from src.dependencies import get_settings
    from src.app import app

    get_settings.cache_clear()
    app.dependency_overrides.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


# --- submitting -----------------------------------------------------------

# PNG signature is enough for filetype's PNG matcher, no full image needed.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_PDF_BYTES = b"%PDF-1.4\n" + b"\x00" * 32


def test_submitting_stores_the_entry_without_any_user_reference(client):
    with patch("src.routes.feedback.repo.create_feedback", return_value=5) as anlegen:
        r = client.post(
            "/feedback",
            data={"category": "bug", "message": "Upload haengt", "page_path": "/workspace/abc"},
        )

    assert r.status_code == 200
    assert r.json() == {"id": 5}
    anlegen.assert_called_once_with(
        category="bug", message="Upload haengt", contact=None, username=None,
        page_path="/workspace/abc",
    )


def test_an_empty_message_is_refused(client):
    with patch("src.routes.feedback.repo.create_feedback") as anlegen:
        r = client.post("/feedback", data={"category": "bug", "message": "   "})

    assert r.status_code == 400
    anlegen.assert_not_called()


def test_an_unknown_category_is_refused(client):
    with patch("src.routes.feedback.repo.create_feedback") as anlegen:
        r = client.post("/feedback", data={"category": "sonstwas", "message": "Test"})

    assert r.status_code == 400
    anlegen.assert_not_called()


def test_contact_is_optional(client):
    with patch("src.routes.feedback.repo.create_feedback", return_value=1) as anlegen:
        r = client.post("/feedback", data={"category": "idea", "message": "Mehr Farben bitte"})

    assert r.status_code == 200
    anlegen.assert_called_once_with(
        category="idea", message="Mehr Farben bitte", contact=None, username=None, page_path=None,
    )


def test_submitting_without_a_session_is_refused(client_ohne_sitzung):
    r = client_ohne_sitzung.post("/feedback", data={"category": "bug", "message": "Test"})
    assert r.status_code == 401


def test_include_username_attaches_the_login_name(client):
    with patch("src.routes.feedback.repo.create_feedback", return_value=1) as anlegen:
        r = client.post(
            "/feedback",
            data={"category": "bug", "message": "Test", "include_username": "true"},
        )

    assert r.status_code == 200
    anlegen.assert_called_once_with(
        category="bug", message="Test", contact=None, username="max.mustermann", page_path=None,
    )


def test_username_stays_off_by_default(client):
    with patch("src.routes.feedback.repo.create_feedback", return_value=1) as anlegen:
        r = client.post("/feedback", data={"category": "bug", "message": "Test"})

    assert r.status_code == 200
    assert anlegen.call_args.kwargs["username"] is None


def test_an_attached_screenshot_is_stored(client):
    with patch("src.routes.feedback.repo.create_feedback", return_value=7) as anlegen, \
         patch("src.routes.feedback.storage.save_feedback_attachment_from_path",
               return_value="feedback/7/abc.png") as speichern, \
         patch("src.routes.feedback.repo.add_attachment") as anhaengen:
        r = client.post(
            "/feedback",
            data={"category": "bug", "message": "Sieht kaputt aus"},
            files=[("files", ("screen.png", _PNG_BYTES, "image/png"))],
        )

    assert r.status_code == 200
    anlegen.assert_called_once()
    speichern.assert_called_once()
    assert speichern.call_args.args[0] == 7
    anhaengen.assert_called_once_with(
        feedback_id=7, filename="screen.png", content_type="image/png",
        size_bytes=len(_PNG_BYTES), storage_key="feedback/7/abc.png",
    )


def test_a_pdf_attachment_is_accepted_too(client):
    with patch("src.routes.feedback.repo.create_feedback", return_value=7), \
         patch("src.routes.feedback.storage.save_feedback_attachment_from_path",
               return_value="feedback/7/abc.pdf"), \
         patch("src.routes.feedback.repo.add_attachment") as anhaengen:
        r = client.post(
            "/feedback",
            data={"category": "bug", "message": "Log anbei"},
            files=[("files", ("log.pdf", _PDF_BYTES, "application/pdf"))],
        )

    assert r.status_code == 200
    anhaengen.assert_called_once()


def test_a_disallowed_file_type_is_refused(client):
    with patch("src.routes.feedback.repo.create_feedback") as anlegen:
        r = client.post(
            "/feedback",
            data={"category": "bug", "message": "Test"},
            files=[("files", ("script.exe", b"MZ" + b"\x00" * 32, "application/octet-stream"))],
        )

    assert r.status_code == 400
    anlegen.assert_not_called()


def test_content_not_matching_the_extension_is_refused(client):
    with patch("src.routes.feedback.repo.create_feedback") as anlegen:
        r = client.post(
            "/feedback",
            data={"category": "bug", "message": "Test"},
            files=[("files", ("fake.png", b"not actually a png" + b"\x00" * 32, "image/png"))],
        )

    assert r.status_code == 400
    anlegen.assert_not_called()


def test_more_than_ten_files_is_refused(client):
    dateien = [("files", (f"s{i}.png", _PNG_BYTES, "image/png")) for i in range(11)]
    with patch("src.routes.feedback.repo.create_feedback") as anlegen:
        r = client.post(
            "/feedback", data={"category": "bug", "message": "Test"}, files=dateien,
        )

    assert r.status_code == 400
    anlegen.assert_not_called()


# --- admin view -------------------------------------------------------------

def test_a_plain_user_may_not_list_feedback(client):
    r = client.get("/admin/feedback")
    assert r.status_code == 403


def test_admin_sees_the_list(admin_client):
    zeilen = [{"id": 1, "category": "bug", "message": "x", "contact": None,
               "page_path": None, "status": "open", "created_at": "2026-08-31T10:00:00"}]
    with patch("src.routes.admin.feedback.repo.list_feedback", return_value=zeilen):
        r = admin_client.get("/admin/feedback")

    assert r.status_code == 200
    assert r.json()["feedback"] == zeilen


def test_setting_the_status_of_an_unknown_entry_is_not_found(admin_client):
    with patch("src.routes.admin.feedback.repo.set_feedback_status", return_value=False) as setzen:
        r = admin_client.patch("/admin/feedback/9", json={"status": "done"})

    assert r.status_code == 404
    setzen.assert_called_once_with(9, "done")


def test_parking_works(admin_client):
    with patch("src.routes.admin.feedback.repo.set_feedback_status", return_value=True) as setzen:
        r = admin_client.patch("/admin/feedback/9", json={"status": "parked"})

    assert r.status_code == 200
    setzen.assert_called_once_with(9, "parked")


def test_an_unknown_status_is_rejected(admin_client):
    with patch("src.routes.admin.feedback.repo.set_feedback_status") as setzen:
        r = admin_client.patch("/admin/feedback/9", json={"status": "maybe"})

    assert r.status_code == 422
    setzen.assert_not_called()


def test_open_count(admin_client):
    with patch("src.routes.admin.feedback.repo.count_open_feedback", return_value=3):
        r = admin_client.get("/admin/feedback/open-count")

    assert r.status_code == 200
    assert r.json() == {"open": 3}


def test_a_plain_user_may_not_count_feedback(client):
    r = client.get("/admin/feedback/open-count")
    assert r.status_code == 403


def test_deleting_an_unknown_entry_is_not_found(admin_client):
    with patch("src.routes.admin.feedback.repo.delete_feedback", return_value=False) as loeschen:
        r = admin_client.delete("/admin/feedback/9")

    assert r.status_code == 404
    loeschen.assert_called_once_with(9)


def test_deleting_works(admin_client):
    with patch("src.routes.admin.feedback.repo.delete_feedback", return_value=True) as loeschen:
        r = admin_client.delete("/admin/feedback/9")

    assert r.status_code == 200
    loeschen.assert_called_once_with(9)


def test_downloading_an_unknown_attachment_is_not_found(admin_client):
    with patch("src.routes.admin.feedback.repo.get_attachment", return_value=None):
        r = admin_client.get("/admin/feedback/attachments/9")
    assert r.status_code == 404


def test_downloading_an_attachment_serves_its_bytes(admin_client, tmp_path):
    datei = tmp_path / "screen.png"
    datei.write_bytes(b"\x89PNG\r\n\x1a\n")
    with patch("src.routes.admin.feedback.repo.get_attachment", return_value={
        "id": 5, "filename": "screen.png", "content_type": "image/png",
        "storage_key": str(datei),
    }), patch("src.routes.admin.feedback.USE_S3", False):
        r = admin_client.get("/admin/feedback/attachments/5")

    assert r.status_code == 200
    assert r.content == b"\x89PNG\r\n\x1a\n"
    assert r.headers["content-type"] == "image/png"


def test_a_plain_user_may_not_download_an_attachment(client):
    r = client.get("/admin/feedback/attachments/5")
    assert r.status_code == 403
