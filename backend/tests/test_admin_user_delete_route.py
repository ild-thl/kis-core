"""The delete route in the admin area, above all its locks."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

ADMIN = {"user_id": 1, "email": "admin@example.org", "role": "admin"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.org")

    from src.app import app
    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _nutzer(user_id=7, email="studi@example.org"):
    return {"id": user_id, "email": email, "display_name": "Studi"}


def test_ein_unbekanntes_konto_gibt_vierhundertvier(client):
    with patch("src.routes.admin.users.db.get_user_by_id", return_value=None):
        r = client.delete("/admin/users/999")
    assert r.status_code == 404
    # Without this line the test would pass even with no route at all.
    assert r.json()["detail"] == "User nicht gefunden"


def test_das_eigene_konto_bleibt_stehen(client):
    """Otherwise the admin locks themselves out with one click."""
    with patch("src.routes.admin.users.db.get_user_by_id", return_value=_nutzer(1)), \
         patch("src.routes.admin.users.delete_user_completely") as loeschen:
        r = client.delete("/admin/users/1")
    assert r.status_code == 400
    loeschen.assert_not_called()


def test_das_env_konto_bleibt_stehen(client):
    """It is recreated at startup and is the way back into the system."""
    with patch("src.routes.admin.users.db.get_user_by_id",
               return_value=_nutzer(9, "admin@example.org")), \
         patch("src.routes.admin.users.delete_user_completely") as loeschen:
        r = client.delete("/admin/users/9")
    assert r.status_code == 403
    loeschen.assert_not_called()


def test_grossschreibung_hebelt_den_schutz_des_env_kontos_nicht_aus(client):
    with patch("src.routes.admin.users.db.get_user_by_id",
               return_value=_nutzer(9, "Admin@Example.org")), \
         patch("src.routes.admin.users.delete_user_completely") as loeschen:
        r = client.delete("/admin/users/9")
    assert r.status_code == 403
    loeschen.assert_not_called()


def test_ein_fremdes_konto_wird_geloescht(client):
    with patch("src.routes.admin.users.db.get_user_by_id", return_value=_nutzer()), \
         patch("src.routes.admin.users.delete_user_completely") as loeschen, \
         patch("src.routes.admin.users.delete_user_folder", return_value=3) as dateien:
        r = client.delete("/admin/users/7")
    assert r.status_code == 200
    loeschen.assert_called_once_with(7)
    dateien.assert_called_once_with(7)


def test_die_dateien_gehen_erst_nach_der_datenbank(client):
    """If the database aborts, the files are still there and the flow stays repeatable."""
    reihenfolge = []
    with patch("src.routes.admin.users.db.get_user_by_id", return_value=_nutzer()), \
         patch("src.routes.admin.users.delete_user_completely",
               side_effect=lambda uid: reihenfolge.append("db")), \
         patch("src.routes.admin.users.delete_user_folder",
               side_effect=lambda uid: reihenfolge.append("dateien")):
        client.delete("/admin/users/7")
    assert reihenfolge == ["db", "dateien"]


def test_eine_stolpernde_ablage_kippt_das_loeschen_nicht(client):
    """The account is gone, leftovers in storage are worth a log message."""
    with patch("src.routes.admin.users.db.get_user_by_id", return_value=_nutzer()), \
         patch("src.routes.admin.users.delete_user_completely"), \
         patch("src.routes.admin.users.delete_user_folder", side_effect=OSError("S3 weg")):
        r = client.delete("/admin/users/7")
    assert r.status_code == 200


def test_die_vorschau_nennt_die_zahlen(client):
    zahlen = {"workspaces": 3, "sources": 12, "messages": 240, "jobs": 5, "enrollments": 2}
    with patch("src.routes.admin.users.db.get_user_by_id", return_value=_nutzer()), \
         patch("src.routes.admin.users.count_user_footprint", return_value=zahlen):
        r = client.get("/admin/users/7/deletion-preview")
    assert r.status_code == 200
    assert r.json() == zahlen


def test_die_vorschau_kennt_unbekannte_konten_nicht(client):
    with patch("src.routes.admin.users.db.get_user_by_id", return_value=None):
        r = client.get("/admin/users/999/deletion-preview")
    assert r.status_code == 404
    assert r.json()["detail"] == "User nicht gefunden"
