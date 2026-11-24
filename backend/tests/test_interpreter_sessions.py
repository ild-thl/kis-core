"""Conversations of the interpreter: kept at the account, sentences as whole rows, speech windows."""

from datetime import datetime
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from src.permissions import Permissions


class FakeRepo:
    """The two tables in memory, enough for the routes to be exercised."""

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.turns: dict[str, dict] = {}
        self.n = 0

    def create_session(self, owner_id, left_lang, right_lang, left_name, right_name):
        self.n += 1
        now = datetime.now()
        row = {
            "id": f"s{self.n}", "owner_id": owner_id, "left_lang": left_lang, "right_lang": right_lang,
            "left_name": left_name, "right_name": right_name, "ended_at": None, "created_at": now, "updated_at": now,
        }
        self.sessions[row["id"]] = row
        return dict(row)

    def get_session(self, sid):
        row = self.sessions.get(sid)
        return dict(row) if row else None

    def list_sessions(self, owner_id, limit=50):
        rows = [dict(r) for r in self.sessions.values() if r["owner_id"] == owner_id]
        for row in rows:
            turns = self.list_turns(row["id"])
            row["turn_count"] = len(turns)
            row["first_original"] = turns[0]["original"] if turns else ""
            row["first_translation"] = turns[0]["translation"] if turns else ""
            row["first_side"] = turns[0]["side"] if turns else "left"
        return rows

    def update_session(self, sid, **fields):
        row = self.sessions.get(sid)
        if not row:
            return None
        row.update(fields)
        row["updated_at"] = datetime.now()
        return dict(row)

    def delete_session(self, sid, owner_id):
        row = self.sessions.get(sid)
        if row and row["owner_id"] == owner_id:
            del self.sessions[sid]
            return True
        return False

    def upsert_turn(self, sid, turn):
        now = datetime.now()
        row = {**turn, "session_id": sid, "created_at": self.turns.get(turn["id"], {}).get("created_at", now), "updated_at": now}
        self.turns[turn["id"]] = row
        return dict(row)

    def delete_turn(self, sid, turn_id):
        self.turns.pop(turn_id, None)

    def list_turns(self, sid):
        rows = [dict(t) for t in self.turns.values() if t["session_id"] == sid]
        return sorted(rows, key=lambda t: (t["at"], t["created_at"]))

    def now(self):
        return datetime.now()


class _FakeWhisper:
    seen_language = None

    def transcribe(self, path, response_format="text", language=None):
        _FakeWhisper.seen_language = language
        return '{"text": "Hallo Welt"}'


def _out_of_local_mode(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")


@pytest.fixture
def env(monkeypatch):
    _out_of_local_mode(monkeypatch)
    from src.dependencies import get_current_user, get_settings
    from src.dependencies_rbac import get_user_permissions
    from src.security.auth import verify_auth
    from src.app import app
    import src.routes.interpreter as routes
    import src.features.interpreter.service as service

    fake = FakeRepo()
    monkeypatch.setattr(routes, "repo", fake)
    monkeypatch.setattr(service, "repo", fake)
    monkeypatch.setattr(routes, "enforce_tool_burst", lambda *a, **k: None)
    monkeypatch.setattr("src.dependencies_rbac.is_released_now", lambda key: True)
    monkeypatch.setattr("src.dependencies.resolve_whisper_client", lambda pid=None: _FakeWhisper())

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 7, "email": "a@th-luebeck.de", "role": "staff"}
    app.dependency_overrides[get_user_permissions] = lambda: Permissions(keys=frozenset({"tools.interpreter"}))
    yield TestClient(app), fake
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _turn(side, original, at=1000):
    return {"side": side, "source": "typed", "original": original, "translation": "", "status": "done", "edited": False, "at": at}


def test_gespraech_anlegen_und_satz_speichern(env):
    client, _ = env
    r = client.post("/interpreter/sessions", json={"left_name": "Lehrperson"})
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["turns"] == [] and state["ended"] is False

    r = client.put(f"/interpreter/sessions/{state['id']}/turns/t1", json=_turn("left", "Guten Tag"))
    assert r.status_code == 200, r.text
    assert r.json()["original"] == "Guten Tag"

    # The same sentence written again replaces the first version.
    client.put(f"/interpreter/sessions/{state['id']}/turns/t1", json={**_turn("left", "Guten Tag!"), "translation": "Hello!"})
    r = client.get(f"/interpreter/sessions/{state['id']}")
    assert [(t["original"], t["translation"]) for t in r.json()["turns"]] == [("Guten Tag!", "Hello!")]

    r = client.get("/interpreter/sessions")
    assert r.json()["sessions"][0]["first_original"] == "Guten Tag!"


def test_leer_getippter_satz_verschwindet_wieder(env):
    client, _ = env
    sid = client.post("/interpreter/sessions", json={}).json()["id"]
    client.put(f"/interpreter/sessions/{sid}/turns/t1", json=_turn("left", "Hal"))
    r = client.put(f"/interpreter/sessions/{sid}/turns/t1", json=_turn("left", "   "))
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert client.get(f"/interpreter/sessions/{sid}").json()["turns"] == []


def test_beendetes_gespraech_nimmt_keinen_satz_mehr(env):
    client, _ = env
    sid = client.post("/interpreter/sessions", json={}).json()["id"]
    r = client.patch(f"/interpreter/sessions/{sid}", json={"ended": True})
    assert r.json()["ended"] is True
    assert client.put(f"/interpreter/sessions/{sid}/turns/t9", json=_turn("left", "Noch was")).status_code == 409


def _fuellen(client, sid):
    """Five sentences of four thousand characters, that is exactly the limit."""
    for i in range(5):
        r = client.put(f"/interpreter/sessions/{sid}/turns/t{i}", json=_turn("left", "a" * 4000, at=i))
        assert r.status_code == 200, r.text


def test_volles_gespraech_nimmt_keinen_satz_mehr_an(env):
    client, _ = env
    sid = client.post("/interpreter/sessions", json={}).json()["id"]
    _fuellen(client, sid)
    assert client.put(f"/interpreter/sessions/{sid}/turns/t9", json=_turn("left", "Noch was", at=9)).status_code == 409


def test_korrektur_zaehlt_nicht_zusaetzlich(env):
    client, _ = env
    sid = client.post("/interpreter/sessions", json={}).json()["id"]
    _fuellen(client, sid)
    # The old version of this sentence leaves the count, so a correction always fits.
    assert client.put(f"/interpreter/sessions/{sid}/turns/t0", json=_turn("left", "a" * 4000, at=0)).status_code == 200
    assert client.put(f"/interpreter/sessions/{sid}/turns/t0", json=_turn("left", "Kurz", at=0)).status_code == 200


def test_fremdes_gespraech_bleibt_unsichtbar(env):
    client, fake = env
    fake.create_session(99, "DE", "EN-US", "", "")
    assert client.get("/interpreter/sessions/s1").status_code == 404
    assert client.put("/interpreter/sessions/s1/turns/t1", json=_turn("left", "Hi")).status_code == 404
    assert client.get("/interpreter/sessions").json()["sessions"] == []


def test_loeschen_nimmt_das_gespraech_aus_der_liste(env):
    client, _ = env
    sid = client.post("/interpreter/sessions", json={}).json()["id"]
    assert client.delete(f"/interpreter/sessions/{sid}").status_code == 204
    assert client.get("/interpreter/sessions").json()["sessions"] == []
    assert client.delete(f"/interpreter/sessions/{sid}").status_code == 404


def test_sprachfenster_kommt_als_text_zurueck(env):
    client, _ = env
    r = client.post("/interpreter/transcribe", files={"audio": ("window.webm", BytesIO(b"\x1a\x45\xdf\xa3 audio"), "audio/webm")})
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "Hallo Welt"
    assert _FakeWhisper.seen_language is None


def test_sprachfenster_gibt_whisper_die_sprache_mit(env):
    client, _ = env
    audio = {"audio": ("window.webm", BytesIO(b"\x1a\x45\xdf\xa3 audio"), "audio/webm")}
    r = client.post("/interpreter/transcribe", files=audio, data={"language": "DE"})
    assert r.status_code == 200, r.text
    assert _FakeWhisper.seen_language == "de"
    # Anything that is not a two-letter code stays away from Whisper.
    client.post("/interpreter/transcribe", files=audio, data={"language": "deutsch"})
    assert _FakeWhisper.seen_language is None


def test_satz_eines_anderen_gespraechs_wird_nicht_ueberschrieben(env):
    """A sentence id that lives in another conversation is refused instead of replaced."""
    client, fake = env
    sid = client.post("/interpreter/sessions", json={}).json()["id"]
    fake.upsert_turn = lambda session_id, turn: None

    r = client.put(f"/interpreter/sessions/{sid}/turns/fremd", json=_turn("left", "Hallo"))
    assert r.status_code == 404, r.text


def test_upsert_turn_bleibt_im_eigenen_gespraech(monkeypatch):
    """The conflict branch only fires for the same conversation, and no row means None."""
    from src.features.interpreter import repository as repo

    gesehen: list[str] = []

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            gesehen.append(" ".join(sql.split()))

        def fetchone(self):
            return None

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self, **kwargs):
            return _Cur()

        def commit(self):
            pass

    monkeypatch.setattr(repo, "get_connection", lambda: _Conn())
    assert repo.upsert_turn("s1", {"id": "t1", **_turn("left", "Hallo")}) is None
    assert any("WHERE interpreter_turns.session_id = EXCLUDED.session_id" in sql for sql in gesehen)
