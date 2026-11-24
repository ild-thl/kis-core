"""The task card of the services page: who sees it, what ticks it, what the admin may save."""
import os
import uuid as uuid_modul
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.features.event import tasks
from src.features.event.service import (
    EventValidationError,
    default_config,
    task_card_for,
    tasks_view,
    validate_config,
)

KARTE = {
    "enabled": True, "ignoreWindow": False, "from": "2026-11-13", "until": "2026-11-13",
    "accessCode": "KIS-DEMO-0000", "workspace": "ws-uuid",
}
TAG = date(2026, 11, 13)


# --- pure rules ---------------------------------------------------------------

def test_karte_nur_fuer_konten_aus_dem_code():
    assert task_card_for(KARTE, TAG, "KIS-DEMO-0000")
    assert task_card_for(KARTE, TAG, " kis-demo-0000 ")
    assert not task_card_for(KARTE, TAG, "KIS-ANDERS-1111")
    assert not task_card_for(KARTE, TAG, None)


def test_karte_nur_im_zeitfenster_und_eingeschaltet():
    assert not task_card_for(KARTE, date(2026, 11, 12), "KIS-DEMO-0000")
    assert not task_card_for({**KARTE, "enabled": False}, TAG, "KIS-DEMO-0000")
    assert task_card_for({**KARTE, "ignoreWindow": True}, date(2026, 10, 1), "KIS-DEMO-0000")


def test_fuer_alle_unabhaengig_vom_code():
    alle = {**KARTE, "forEveryone": True}
    assert task_card_for(alle, TAG, None)
    assert task_card_for(alle, TAG, "KIS-ANDERS-1111")
    assert not task_card_for(alle, date(2026, 11, 12), None)


def test_leerer_code_zeigt_niemandem_die_karte():
    assert not task_card_for({**KARTE, "accessCode": ""}, TAG, "")


def test_fertig_erst_mit_allen_drei_aufgaben():
    teil = tasks_view({"question": 1, "praesentation": 2}, "ws")
    assert teil["completedAt"] is None
    voll = tasks_view({"question": 1, "praesentation": 2, "screencast": 3, "alt": 9}, "ws")
    assert voll["completedAt"] == 3
    assert "alt" not in voll["done"]


def test_validierung_ergaenzt_fehlende_karte():
    config = default_config()
    config.pop("taskCard")
    assert validate_config(config)["taskCard"]["enabled"] is False


def test_validierung_lehnt_falsches_datum_ab():
    config = default_config()
    config["taskCard"] = {**KARTE, "from": "13.11.2026"}
    with pytest.raises(EventValidationError):
        validate_config(config)


# --- routes -------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    from src.app import app
    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth

    gesetzt: list[tuple[int, str]] = []
    monkeypatch.setattr(tasks, "card_for", lambda user_id: KARTE)
    monkeypatch.setattr(tasks, "add_done", lambda user_id, task_id: gesetzt.append((user_id, task_id)))
    monkeypatch.setattr(tasks, "done_for", lambda user_id: {task_id: 1 for _, task_id in gesetzt})
    monkeypatch.setattr(tasks, "workspace_title", lambda workspace_uuid: "Projektmanagement")
    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 7, "email": "demo@kis.local", "role": "staff"}
    yield TestClient(app), gesetzt
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_demo_oeffnen_setzt_haken(client):
    http, gesetzt = client
    antwort = http.post("/event-tasks/praesentation")
    assert antwort.status_code == 200
    assert gesetzt == [(7, "praesentation")]
    assert "praesentation" in antwort.json()["done"]
    assert antwort.json()["workspaceTitle"] == "Projektmanagement"


def test_frage_laesst_sich_nicht_vom_browser_abhaken(client):
    http, gesetzt = client
    assert http.post("/event-tasks/question").status_code == 404
    assert gesetzt == []


def test_ohne_karte_kein_haken(client, monkeypatch):
    http, gesetzt = client
    monkeypatch.setattr(tasks, "card_for", lambda user_id: None)
    antwort = http.post("/event-tasks/screencast")
    assert antwort.json() == {"visible": False}
    assert gesetzt == []


def test_ohne_sitzung_gesperrt():
    from src.app import app
    from src.dependencies import get_settings

    get_settings.cache_clear()
    app.dependency_overrides.clear()
    assert TestClient(app).get("/event-tasks").status_code == 401


def test_frage_zaehlt_in_jedem_workspace(monkeypatch):
    gesetzt = []
    monkeypatch.setattr(tasks, "card_for", lambda user_id: KARTE)
    monkeypatch.setattr(tasks, "add_done", lambda user_id, task_id: gesetzt.append(task_id))
    tasks.mark_question(7, "eigener-workspace")
    assert gesetzt == ["question"]


def test_frage_ohne_karte_zaehlt_nicht(monkeypatch):
    gesetzt = []
    monkeypatch.setattr(tasks, "card_for", lambda user_id: None)
    monkeypatch.setattr(tasks, "add_done", lambda user_id, task_id: gesetzt.append(task_id))
    tasks.mark_question(7, "ws-uuid")
    assert gesetzt == []


def test_fehler_beim_haken_bricht_den_chat_nicht(monkeypatch):
    def kaputt(user_id):
        raise RuntimeError("db weg")
    monkeypatch.setattr(tasks, "card_for", kaputt)
    tasks.mark_question(7, "ws-uuid")


# --- storage ------------------------------------------------------------------

@pytest.fixture
def konto_am_code():
    """A code with a workspace plus an account made from it, all gone afterwards."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("kein DATABASE_URL gesetzt (Test braucht echtes Postgres)")
    from src.core.db.pool import get_connection
    from src.core.db.schema import init_db
    from src.features.access_codes import repository as codes

    init_db()
    kennung = uuid_modul.uuid4().hex[:8]
    code = f"KIS-TASK-{kennung.upper()}"
    code_id = codes.create_code(
        code=code, label="Aufgabenkarte Test", role="staff", custom_role_id=None, max_uses=5,
        valid_until=datetime.now() + timedelta(days=1), access_hours=24, show_credentials=False,
        show_evaluation=False, created_by=0,
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, display_name, email, active, role, access_code_id) "
                "VALUES (%s, 'Test Aufgaben', %s, 1, 'staff', %s) RETURNING id",
                (f"test.aufgaben.{kennung}", f"test.aufgaben.{kennung}@demo.kis.local", code_id),
            )
            user_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO aia_workspaces (uuid, user_id, title) VALUES (%s, %s, 'Aufgaben-Test') RETURNING id",
                (f"ws-{kennung}", user_id),
            )
            ws_id = cur.fetchone()[0]
        conn.commit()
    codes.set_code_workspaces(code_id, [ws_id])
    yield {"code": code, "user_id": user_id, "workspace": f"ws-{kennung}"}
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM aia_workspaces WHERE id = %s", (ws_id,))
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
            cur.execute("DELETE FROM access_codes WHERE id = %s", (code_id,))
        conn.commit()


def test_haken_bleiben_je_konto_gespeichert(konto_am_code):
    user_id = konto_am_code["user_id"]
    assert tasks.user_access_code(user_id) == konto_am_code["code"]
    tasks.add_done(user_id, "screencast")
    tasks.add_done(user_id, "screencast")
    assert list(tasks.done_for(user_id)) == ["screencast"]


def test_workspaces_des_codes_zur_auswahl(konto_am_code):
    assert tasks.workspace_title(konto_am_code["workspace"]) == "Aufgaben-Test"
    auswahl = tasks.workspaces_for_code(konto_am_code["code"].lower())
    assert auswahl == [{"uuid": konto_am_code["workspace"], "title": "Aufgaben-Test"}]


# --- chat and admin -------------------------------------------------------------

def test_frage_zaehlt_auch_ohne_anbieter(monkeypatch):
    """The chat's provider lookup fails with 503, the question task is ticked anyway."""
    from fastapi import HTTPException
    from src.app import app
    from src.dependencies import get_current_user, get_llm_client, get_settings
    from src.security.auth import verify_auth

    gesehen = []
    monkeypatch.setattr(tasks, "mark_question", lambda user_id, ws: gesehen.append((user_id, ws)))

    def kein_anbieter():
        raise HTTPException(status_code=503, detail="kein Anbieter")

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 7, "email": "demo@kis.local", "role": "staff"}
    app.dependency_overrides[get_llm_client] = kein_anbieter
    try:
        antwort = TestClient(app).post("/ai-assistant/workspaces/ws-uuid/chat", json={"message": "Was ist ein Meilenstein?"})
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
    assert antwort.status_code == 503
    assert gesehen == [(7, "ws-uuid")]


@pytest.fixture
def admin_client(monkeypatch):
    from src.app import app
    from src.dependencies import get_current_user, get_settings
    from src.features.event import repository as repo
    from src.security.auth import verify_auth

    gespeichert = {}
    monkeypatch.setattr(repo, "get_config", lambda: {**default_config(), "taskCard": KARTE})
    monkeypatch.setattr(repo, "save_config", lambda config: gespeichert.update(config))
    monkeypatch.setattr(tasks, "workspaces_for_code", lambda code: [{"uuid": "ws-uuid", "title": f"von {code}"}])
    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "email": "admin@example.org", "role": "admin"}
    yield TestClient(app), gespeichert
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_auswahl_nur_fuer_den_gespeicherten_code(admin_client):
    http, _ = admin_client
    antwort = http.get("/admin/event/task-workspaces", params={"code": "KIS-FREMD-9999"})
    assert antwort.json() == {"workspaces": [{"uuid": "ws-uuid", "title": "von KIS-DEMO-0000"}]}


def test_fremder_workspace_wird_beim_speichern_geleert(admin_client):
    http, gespeichert = admin_client
    config = {**default_config(), "taskCard": {**KARTE, "workspace": "fremd"}}
    assert http.put("/admin/event", json=config).status_code == 200
    assert gespeichert["taskCard"]["workspace"] == ""
    config["taskCard"]["workspace"] = "ws-uuid"
    http.put("/admin/event", json=config)
    assert gespeichert["taskCard"]["workspace"] == "ws-uuid"


def test_eigene_haken_zuruecksetzen(admin_client, monkeypatch):
    http, _ = admin_client
    geleert = []
    monkeypatch.setattr(tasks, "delete_for", lambda user_id: geleert.append(user_id))
    assert http.delete("/admin/event/tasks/me").status_code == 200
    assert geleert == [1]


def test_haken_einzeln_loeschen(konto_am_code):
    user_id = konto_am_code["user_id"]
    tasks.add_done(user_id, "question")
    tasks.delete_for(user_id)
    assert tasks.done_for(user_id) == {}


# --- tile placement -------------------------------------------------------------

def test_nirgends_platzierte_kachel_verlaesst_den_server_nicht():
    from src.features.event.service import public_view

    config = validate_config(default_config())
    config["eventBlock"] = {**config["eventBlock"], "enabled": True, "ignoreWindow": True}
    config["eventBlock"]["tiles"][1]["placement"] = "none"
    sicht = public_view(config, TAG)
    assert [t["id"] for t in sicht["eventBlock"]["tiles"]] == ["demo"]
    assert sicht["stamp"] is None


def test_alte_ausgeblendete_kachel_wird_zu_nirgends():
    config = default_config()
    tile = config["eventBlock"]["tiles"][0]
    tile.pop("placement")
    tile["hidden"] = True
    gespeichert = validate_config(config)["eventBlock"]["tiles"][0]
    assert gespeichert["placement"] == "none"
    assert "hidden" not in gespeichert


def test_nur_ein_banner():
    config = default_config()
    for tile in config["eventBlock"]["tiles"]:
        tile["placement"] = "banner"
    with pytest.raises(EventValidationError):
        validate_config(config)
