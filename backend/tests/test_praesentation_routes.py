"""The routes: what is refused, and that every change only touches its own file."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.features.praesentation.schemas import Body, Outline, OutlineRow, Slide
from src.permissions import Permissions

THL = Path("src/features/praesentation/assets/thl.pptx").read_bytes()
UUID = "a" * 32


def _out_of_local_mode(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")


class FakeAblage:
    def __init__(self):
        self.dateien = {}

    def save_job_file(self, user_id, job_uuid, filename, data):
        self.dateien[(user_id, job_uuid, filename)] = data
        return f"users/{user_id}/jobs/{job_uuid}/{filename}"

    def get_job_file(self, user_id, job_uuid, filename):
        try:
            return self.dateien[(user_id, job_uuid, filename)]
        except KeyError as e:
            raise FileNotFoundError(filename) from e

    def job_file_exists(self, user_id, job_uuid, filename):
        return (user_id, job_uuid, filename) in self.dateien

    def delete_job_file(self, user_id, job_uuid, filename):
        self.dateien.pop((user_id, job_uuid, filename), None)


@pytest.fixture
def env(monkeypatch):
    _out_of_local_mode(monkeypatch)
    from src.app import app
    from src.dependencies import get_current_user, get_settings
    from src.dependencies_rbac import get_user_permissions
    from src.features.praesentation import store
    from src.security.auth import verify_auth
    import src.routes._shared as shared
    import src.routes.praesentation.start as start_route
    import src.routes.praesentation.outline as outline_route
    import src.routes.praesentation.slides as slides_route
    import src.routes.praesentation.vorlagen as vorlagen_route

    from src.services import job_files

    ablage = FakeAblage()
    # The shared sources go through job_files, not the tool's store.
    for modul in (store, job_files):
        for name in ("save_job_file", "get_job_file", "job_file_exists"):
            monkeypatch.setattr(modul, name, getattr(ablage, name))
    monkeypatch.setattr("src.dependencies_rbac.is_released_now", lambda key: True)

    jobs: dict[str, dict] = {}
    gestartet: list[tuple] = []
    monkeypatch.setattr(shared.db, "get_job", lambda uuid: jobs.get(uuid))
    monkeypatch.setattr(start_route.db, "has_active_job_for_tool", lambda uid, tools: any(
        j["status"] in ("pending", "running", "queued", "waiting_retry") for j in jobs.values()))
    monkeypatch.setattr(start_route.db, "create_job",
                        lambda uuid, uid, tool, name, locale="de": jobs.__setitem__(
                            uuid, {"job_uuid": uuid, "user_id": uid, "tool": tool, "status": "pending"}))
    for modul in (start_route, outline_route, slides_route):
        monkeypatch.setattr(modul.db, "set_job_celery_task_id", lambda *a, **k: None)
        monkeypatch.setattr(modul.db, "update_job_status", lambda uuid, status, **k: jobs[uuid].__setitem__("status", status))
    monkeypatch.setattr(slides_route.db, "reset_attempts", lambda uuid: None)
    monkeypatch.setattr(outline_route.db, "reset_attempts", lambda uuid: None)
    monkeypatch.setattr(slides_route.db, "reset_job_to_awaiting", lambda uuid: jobs[uuid].__setitem__("status", "awaiting_user"))

    class _Task:
        def __init__(self, name):
            self.name = name

        def apply_async(self, args):
            gestartet.append((self.name, list(args)))
            return type("T", (), {"id": "celery-1"})()

    monkeypatch.setattr(start_route, "run_praesentation_outline", _Task("outline"))
    monkeypatch.setattr(outline_route, "run_praesentation_build", _Task("build"))
    monkeypatch.setattr(slides_route, "run_praesentation_build", _Task("build"))
    monkeypatch.setattr(slides_route, "clear_cancel", lambda uuid: None)
    monkeypatch.setattr(outline_route, "clear_cancel", lambda uuid: None)


    vorlagen: dict[str, dict] = {}
    monkeypatch.setattr(vorlagen_route.vorlagen_repo, "list_for_user", lambda uid: list(vorlagen.values()))
    monkeypatch.setattr(vorlagen_route.vorlagen_repo, "count", lambda uid: len(vorlagen))
    monkeypatch.setattr(vorlagen_route.vorlagen_repo, "get", lambda uid, vid: vorlagen.get(vid))
    monkeypatch.setattr(vorlagen_route.vorlagen_repo, "create", lambda uid, name, stil: vorlagen.setdefault(
        f"v{len(vorlagen) + 1}", {"id": f"v{len(vorlagen) + 1}", "name": name, "stiltext": stil}))
    monkeypatch.setattr(vorlagen_route.vorlagen_repo, "delete", lambda uid, vid: vorlagen.pop(vid, None) is not None)
    monkeypatch.setattr(vorlagen_route.vorlagen, "speichere", lambda *a, **k: None)
    monkeypatch.setattr(vorlagen_route.vorlagen, "loesche", lambda *a, **k: None)
    monkeypatch.setattr(vorlagen_route.vorlagen, "deckblatt_vorschau", lambda *a, **k: b"png")
    monkeypatch.setattr(vorlagen_route.vorlagen, "lade_meta", lambda uid, vid: {"roles": ["text"], "hasImages": False})

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 7, "email": "a@th-luebeck.de", "role": "staff"}
    app.dependency_overrides[get_user_permissions] = lambda: Permissions(keys=frozenset({"tools.praesentation"}))
    yield TestClient(app), jobs, gestartet, ablage, vorlagen
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _params(**kw):
    grund = {"language": "de", "instructions": "", "notes": False, "template_id": "thl"}
    grund.update(kw)
    return json.dumps(grund)


def client_von(env):
    return env[0]


def _start(client):
    return client.post("/praesentation/start", data={"params": _params(), "mode": "files"},
                       files={"files": ("kapitel.txt", "Über den Regelkreis.".encode(), "text/plain")})


class TestStart:
    def _gestartet_mit(self, env, monkeypatch, **params):
        import src.routes.praesentation.start as start_route
        from src.features.praesentation import store

        client, jobs, *_ = env
        # Each start stands alone, an earlier one would count as running.
        jobs.clear()
        monkeypatch.setattr(start_route, "enforce_open_jobs", lambda *a, **k: None)
        monkeypatch.setattr(start_route, "create_counted_job", lambda uuid, uid, tool, name, locale="de": jobs.__setitem__(
            uuid, {"job_uuid": uuid, "user_id": uid, "tool": tool, "status": "pending"}))
        antwort = client.post("/praesentation/start", data={"params": _params(**params), "mode": "files"},
                              files={"files": ("kapitel.txt", "Über den Regelkreis.".encode(), "text/plain")})
        assert antwort.status_code == 200, antwort.text
        return store.load_params(7, antwort.json()["job_uuid"])

    def test_ohne_eigenen_bildstil_gilt_der_der_vorlage(self, env, monkeypatch):
        from src.features.praesentation import vorlagen

        gespeichert = self._gestartet_mit(env, monkeypatch)
        assert gespeichert.style_text == vorlagen.systemvorlage()[1]["style_text"]

    def test_ein_geaenderter_bildstil_gewinnt_auch_leer(self, env, monkeypatch):
        assert self._gestartet_mit(env, monkeypatch, style_text="Watercolour, soft blue").style_text == "Watercolour, soft blue"
        assert self._gestartet_mit(env, monkeypatch, style_text="").style_text == ""

    def test_zu_langer_bildstil_wird_abgewiesen(self, env):
        client, *_ = env
        antwort = client.post("/praesentation/start", data={"params": _params(style_text="x" * 1001), "mode": "files"},
                              files={"files": ("kapitel.txt", "Über den Regelkreis.".encode(), "text/plain")})
        assert antwort.status_code == 422








    def test_ein_nicht_waehlbarer_ki_anbieter_wird_abgewiesen(self, env, monkeypatch):
        import src.routes.praesentation.start as start_route

        client, *_ = env
        monkeypatch.setattr(start_route.feature_provider_choices, "is_eligible", lambda f, pid: False)
        antwort = client.post("/praesentation/start",
                              data={"params": _params(llm_provider_id=99), "mode": "files"},
                              files={"files": ("kapitel.txt", "Über den Regelkreis.".encode(), "text/plain")})
        assert antwort.status_code == 400

    def test_ohne_recht(self, env, monkeypatch):
        client, *_ = env
        from src.app import app
        from src.dependencies_rbac import get_user_permissions
        app.dependency_overrides[get_user_permissions] = lambda: Permissions(keys=frozenset())
        assert _start(client).status_code == 403


def _mit_gliederung(env, status="awaiting_user"):
    client, jobs, gestartet, ablage, _ = env
    from src.features.praesentation import store
    jobs[UUID] = {"job_uuid": UUID, "user_id": 7, "tool": "praesentation", "status": status}
    rollen = ["deckblatt", "text", "text", "text", "text", "abschluss"]
    store.save_outline(7, UUID, Outline(title="Deck", rows=[
        OutlineRow(id=f"s{i + 1}", role=r, title=f"T{i}", gist="g") for i, r in enumerate(rollen)]))
    from src.features.praesentation import vorlage
    from src.features.praesentation.schemas import PraesentationParams
    store.save_params(7, UUID, PraesentationParams())
    from src.services import sources as quellen
    from src.services.source_reading import Piece, Source

    quellen.save_sources(7, UUID, [Source(dateiname="a.txt", fassung="x", text="Quelle",
                                          stuecke=[Piece(seite=1, von=0, bis=6)], seiten=1)])
    store.save_template(7, UUID, THL)
    store.save_template_meta(7, UUID, vorlage.analysiere(THL))
    return client, jobs, gestartet, ablage


class TestOutline:
    def test_stand_liefert_gliederung(self, env):
        client, *_ = _mit_gliederung(env)
        antwort = client.get(f"/praesentation/{UUID}")
        assert antwort.status_code == 200
        assert len(antwort.json()["outline"]["rows"]) == 6 and antwort.json()["slides"] == []

    def test_fremder_auftrag_ist_404(self, env):
        client, jobs, *_ = _mit_gliederung(env)
        jobs[UUID]["user_id"] = 8
        assert client.get(f"/praesentation/{UUID}").status_code == 404

    def test_speichern_prueft_und_vergibt_ids(self, env):
        client, jobs, gestartet, ablage = _mit_gliederung(env)
        rows = [{"id": "s1", "role": "deckblatt", "title": "A", "gist": ""},
                {"id": "", "role": "text", "title": "Neu", "gist": ""}] + [
            {"id": f"s{i}", "role": "text", "title": f"T{i}", "gist": ""} for i in range(2, 6)] + [
            {"id": "s6", "role": "abschluss", "title": "E", "gist": ""}]
        antwort = client.put(f"/praesentation/{UUID}/outline", json={"title": "Deck", "subtitle": "", "rows": rows})
        assert antwort.status_code == 200
        ids = [r["id"] for r in antwort.json()["rows"]]
        assert ids[1] == "s7" and antwort.json()["rows"][-1]["role"] == "abschluss"
        assert json.loads(ablage.get_job_file(7, UUID, "user_outline.json"))["rows"][1]["title"] == "Neu"

    def test_zu_wenige_zeilen(self, env):
        client, *_ = _mit_gliederung(env)
        rows = [{"id": "s1", "role": "deckblatt", "title": "A", "gist": ""}]
        assert client.put(f"/praesentation/{UUID}/outline", json={"title": "D", "subtitle": "", "rows": rows}).status_code == 422

    def test_folienschritt_haelt_die_untergrenze_nicht_mehr_hoch(self, env):
        """Once slides exist the outline follows the deck, so only the hard cap still counts."""
        client, jobs, gestartet, ablage = _mit_gliederung(env)
        from src.features.praesentation import store
        from src.features.praesentation.schemas import Slide
        store.save_slides(7, UUID, [Slide(id=f"s{i}", role="text", layout=3, title=f"T{i}") for i in range(1, 3)])
        rows = [{"id": "s1", "role": "deckblatt", "title": "T1", "gist": ""},
                {"id": "s2", "role": "abschluss", "title": "T2", "gist": ""}]
        antwort = client.put(f"/praesentation/{UUID}/outline", json={"title": "Deck", "subtitle": "", "rows": rows})
        assert antwort.status_code == 200
        assert len(antwort.json()["rows"]) == 2

    def test_build_startet_den_task(self, env):
        client, jobs, gestartet, _ = _mit_gliederung(env)
        antwort = client.post(f"/praesentation/{UUID}/build")
        assert antwort.status_code == 200
        assert gestartet == [("build", [UUID, 7, "de", 1, 0, None, False])]
        assert jobs[UUID]["status"] == "pending"

    def test_build_waehrend_es_laeuft(self, env):
        client, *_ = _mit_gliederung(env, status="running")
        assert client.post(f"/praesentation/{UUID}/build").status_code == 409

    def test_build_behaelt_das_fertigstellen_bei_wiederaufnahme(self, env):
        """Resuming a job parked mid-finalize must re-queue with the same finalize intent."""
        # "paused" is the row production writes for a parked run, "waiting_retry" is still busy per nicht_beschaeftigt.
        client, jobs, gestartet, ablage = _mit_gliederung(env, status="paused")
        jobs[UUID]["progress"] = json.dumps({"step": "bau", "final": True})
        antwort = client.post(f"/praesentation/{UUID}/build")
        assert antwort.status_code == 200
        assert gestartet == [("build", [UUID, 7, "de", 1, 0, None, True])]

    def test_build_auf_fertigem_auftrag_startet_ohne_fertigstellen(self, env):
        """A finished job's own leftover finalize flag must not silently re-finalize a fresh rebuild."""
        client, jobs, gestartet, ablage = _mit_gliederung(env, status="success")
        jobs[UUID]["progress"] = json.dumps({"step": "done", "final": True})
        antwort = client.post(f"/praesentation/{UUID}/build")
        assert antwort.status_code == 200
        assert gestartet == [("build", [UUID, 7, "de", 1, 0, None, False])]

    def test_build_ueberlebt_kaputten_fortschritt(self, env):
        """An unreadable progress column must fall back to no finalize intent, not a 500."""
        client, jobs, gestartet, ablage = _mit_gliederung(env, status="failed")
        jobs[UUID]["progress"] = "kaputt"
        antwort = client.post(f"/praesentation/{UUID}/build")
        assert antwort.status_code == 200
        assert gestartet == [("build", [UUID, 7, "de", 1, 0, None, False])]

    def test_regen_zeile(self, env, monkeypatch):
        client, *_ = _mit_gliederung(env)
        import src.routes.praesentation.outline as outline_route
        monkeypatch.setattr(outline_route, "llm_antwort", lambda nachrichten, anbieter=None: '{"title": "Neu", "gist": "Anders"}')
        antwort = client.post(f"/praesentation/{UUID}/outline/s2/regen", json={"messages": [], "selected_text": ""})
        assert antwort.json() == {"id": "s2", "title": "Neu", "gist": "Anders"}


def _mit_folien(env):
    client, jobs, gestartet, ablage = _mit_gliederung(env)
    from src.features.praesentation import store
    rollen = ["deckblatt", "text", "text", "text", "text", "abschluss"]
    store.save_slides(7, UUID, [Slide(id=f"s{i + 1}", role=r, layout=0 if r in ("deckblatt", "abschluss") else 3,
                                      title=f"T{i}", body=None if r in ("deckblatt", "abschluss") else Body(items=["a"]))
                                for i, r in enumerate(rollen)])
    store.save_deck(7, UUID, b"PKdeck")
    return client, jobs, gestartet, ablage


class TestSlides:
    def test_folie_speichern_rendert_die_vorschau(self, env, monkeypatch):
        client, jobs, gestartet, ablage = _mit_folien(env)
        import src.routes.praesentation.slides as slides_route
        monkeypatch.setattr(slides_route.vorschau, "einzeln", lambda *a, **k: b"neu-png")
        s = {"id": "s2", "role": "text", "layout": 3, "title": "Anders", "subtitle": "",
             "body": {"kind": "bullets", "items": ["b", "c"]}, "columns": [], "images": [], "notes": ""}
        antwort = client.put(f"/praesentation/{UUID}/slides/s2", json=s)
        assert antwort.status_code == 200
        assert ablage.get_job_file(7, UUID, "preview/s2.png") == b"neu-png"
        gespeichert = json.loads(ablage.get_job_file(7, UUID, "user_slides.json"))
        assert gespeichert[1]["title"] == "Anders" and gespeichert[1]["role"] == "text"

    def test_rolle_und_layout_kann_der_nutzer_nicht_aendern(self, env, monkeypatch):
        client, jobs, gestartet, ablage = _mit_folien(env)
        import src.routes.praesentation.slides as slides_route
        monkeypatch.setattr(slides_route.vorschau, "einzeln", lambda *a, **k: b"png")
        s = {"id": "s2", "role": "deckblatt", "layout": 0, "title": "X", "subtitle": "", "body": None,
             "columns": [], "images": [], "notes": ""}
        client.put(f"/praesentation/{UUID}/slides/s2", json=s)
        gespeichert = json.loads(ablage.get_job_file(7, UUID, "user_slides.json"))
        assert gespeichert[1]["role"] == "text" and gespeichert[1]["layout"] == 3

    def test_loeschen_und_reihenfolge(self, env):
        client, jobs, gestartet, ablage = _mit_folien(env)
        assert client.delete(f"/praesentation/{UUID}/slides/s3").status_code == 200
        antwort = client.put(f"/praesentation/{UUID}/slides/order", json={"ids": ["s1", "s4", "s2", "s5", "s6"]})
        assert antwort.status_code == 200
        ids = [s["id"] for s in json.loads(ablage.get_job_file(7, UUID, "user_slides.json"))]
        assert ids == ["s1", "s4", "s2", "s5", "s6"]

    def test_reihenfolge_setzt_einen_fertigen_auftrag_zurueck(self, env):
        """A finished job must reopen once the order changes, or the download keeps the stale file."""
        client, jobs, gestartet, ablage = _mit_folien(env)
        jobs[UUID]["status"] = "success"
        antwort = client.put(f"/praesentation/{UUID}/slides/order", json={"ids": ["s1", "s3", "s2", "s4", "s5", "s6"]})
        assert antwort.status_code == 200
        assert jobs[UUID]["status"] == "awaiting_user"

    def test_verschieben_rendert_die_folien_mit_neuer_nummer(self, env, monkeypatch):
        client, jobs, gestartet, ablage = _mit_folien(env)
        import src.routes.praesentation.slides as slides_route
        monkeypatch.setattr(slides_route.vorschau, "mehrere",
                            lambda v, a, slides, *r, nummern=(), **k: [f"{s.id}:{n}".encode() for s, n in zip(slides, nummern)])
        antwort = client.put(f"/praesentation/{UUID}/slides/order", json={"ids": ["s1", "s3", "s2", "s4", "s5", "s6"]})
        assert antwort.json()["previews"] == ["s3", "s2"]
        assert ablage.get_job_file(7, UUID, "preview/s3.png") == b"s3:2"
        assert ablage.get_job_file(7, UUID, "preview/s2.png") == b"s2:3"

    def test_loeschen_rendert_die_folien_dahinter_neu(self, env, monkeypatch):
        client, jobs, gestartet, ablage = _mit_folien(env)
        import src.routes.praesentation.slides as slides_route
        monkeypatch.setattr(slides_route.vorschau, "mehrere",
                            lambda v, a, slides, *r, nummern=(), **k: [f"{s.id}:{n}".encode() for s, n in zip(slides, nummern)])
        antwort = client.delete(f"/praesentation/{UUID}/slides/s3")
        assert antwort.json()["previews"] == ["s4", "s5", "s6"]
        assert ablage.get_job_file(7, UUID, "preview/s6.png") == b"s6:5"

    def test_deckblatt_darf_nicht_geloescht_werden(self, env):
        client, *_ = _mit_folien(env)
        assert client.delete(f"/praesentation/{UUID}/slides/s1").status_code == 422

    def test_einfuegen_legt_zeile_an_und_startet_den_bau_fuer_die_neue(self, env):
        client, jobs, gestartet, ablage = _mit_folien(env)
        antwort = client.post(f"/praesentation/{UUID}/slides", json={"after": "s2", "title": "Dazwischen"})
        assert antwort.status_code == 200
        neu = antwort.json()["id"]
        rows = json.loads(ablage.get_job_file(7, UUID, "user_outline.json"))["rows"]
        assert [r["id"] for r in rows][:3] == ["s1", "s2", neu] and rows[2]["role"] == "text_mit_bild"
        assert gestartet[-1] == ("build", [UUID, 7, "de", 1, 0, {"text": [neu], "bild": [neu]}, False])

    def test_einfuegen_rotiert_das_layout_weiter(self, env):
        """A role with two layouts must not always land on the first one when slides already use it."""
        client, jobs, gestartet, ablage = _mit_folien(env)
        from src.features.praesentation import store, vorlage
        analyse = vorlage.Analyse(breite=1, hoehe=1, typeface="Arial", layouts=[
            vorlage.Layout(0, "Deck", "deckblatt", []), vorlage.Layout(1, "Text A", "text", []),
            vorlage.Layout(2, "Text B", "text", []), vorlage.Layout(3, "Ende", "abschluss", [])],
            rollen={"deckblatt": [0], "text": [1, 2], "abschluss": [3]})
        store.save_template_meta(7, UUID, analyse)
        store.save_user_slides(7, UUID, [Slide(id="s1", role="deckblatt", layout=0, title="A"),
                                         Slide(id="s2", role="text", layout=1, title="B", body=Body(items=["x"])),
                                         Slide(id="s3", role="abschluss", layout=3, title="C")])
        antwort = client.post(f"/praesentation/{UUID}/slides", json={"after": "s2", "title": "Neu"})
        assert antwort.status_code == 200
        rows = json.loads(ablage.get_job_file(7, UUID, "user_slides.json"))
        neu = next(r for r in rows if r["title"] == "Neu")
        assert neu["layout"] == 2

    def test_einfuegen_ueber_der_obergrenze(self, env):
        client, jobs, gestartet, ablage = _mit_folien(env)
        from src.features.praesentation import store
        store.save_user_slides(7, UUID, [Slide(id=f"s{i}", role="text", layout=3, title="T") for i in range(1, 31)])
        assert client.post(f"/praesentation/{UUID}/slides", json={"after": "s2", "title": "Zu viel"}).status_code == 422

    def test_einfuegen_nimmt_die_anweisung_als_kernaussage(self, env):
        client, jobs, gestartet, ablage = _mit_folien(env)
        antwort = client.post(f"/praesentation/{UUID}/slides",
                              json={"after": "s2", "title": "Kühlung", "instruction": "nur die Zahlen aus Kapitel 4"})
        assert antwort.status_code == 200
        neu = antwort.json()["id"]
        rows = json.loads(ablage.get_job_file(7, UUID, "user_outline.json"))["rows"]
        zeile = next(r for r in rows if r["id"] == neu)
        assert zeile["gist"] == "nur die Zahlen aus Kapitel 4" and zeile["title"] == "Kühlung"



    def test_einfuegen_geht_auch_ohne_titel(self, env):
        """Instruction alone is enough, the model writes the heading itself."""
        client, jobs, gestartet, ablage = _mit_folien(env)
        antwort = client.post(f"/praesentation/{UUID}/slides",
                              json={"after": "s2", "title": "", "instruction": "vergleiche die beiden Verfahren"})
        assert antwort.status_code == 200
        neu = antwort.json()["id"]
        rows = json.loads(ablage.get_job_file(7, UUID, "user_outline.json"))["rows"]
        zeile = next(r for r in rows if r["id"] == neu)
        assert zeile["title"] == "" and zeile["gist"] == "vergleiche die beiden Verfahren"

    def test_einfuegen_ohne_titel_und_ohne_anweisung_wird_abgewiesen(self, env):
        client, *_ = _mit_folien(env)
        antwort = client.post(f"/praesentation/{UUID}/slides", json={"after": "s2", "title": "  ", "instruction": ""})
        assert antwort.status_code == 422


    def test_notizen_abwaehlen_speichert_den_schalter(self, env):
        client, jobs, gestartet, ablage = _mit_folien(env)
        from src.features.praesentation import store
        from src.features.praesentation.schemas import PraesentationParams
        store.save_params(7, UUID, PraesentationParams(notes=True))
        antwort = client.put(f"/praesentation/{UUID}/notes", json={"include": False})
        assert antwort.status_code == 200 and antwort.json() == {"include": False}
        assert store.load_params(7, UUID).notes_include is False
        assert gestartet == [], "der Schalter allein baut nichts neu"

    def test_notizen_wieder_anwaehlen(self, env):
        client, jobs, gestartet, ablage = _mit_folien(env)
        from src.features.praesentation import store
        from src.features.praesentation.schemas import PraesentationParams
        store.save_params(7, UUID, PraesentationParams(notes=True, notes_include=False))
        assert client.put(f"/praesentation/{UUID}/notes", json={"include": True}).status_code == 200
        assert store.load_params(7, UUID).notes_include is True

    def test_schalter_oeffnet_einen_fertigen_auftrag_wieder(self, env):
        """The built file still carries the notes, so it has to be built once more."""
        client, jobs, gestartet, ablage = _mit_folien(env)
        jobs[UUID]["status"] = "success"
        assert client.put(f"/praesentation/{UUID}/notes", json={"include": False}).status_code == 200
        assert jobs[UUID]["status"] == "awaiting_user"

    def test_bild_neu_startet_den_bau_nur_fuer_das_bild(self, env):
        client, jobs, gestartet, _ = _mit_folien(env)
        antwort = client.post(f"/praesentation/{UUID}/slides/s1/image", json={"prompts": []})
        assert antwort.status_code == 200
        assert gestartet[-1] == ("build", [UUID, 7, "de", 1, 0, {"text": [], "bild": ["s1"]}, False])

    def test_bild_neu_uebernimmt_die_beschreibung_aus_dem_dialog(self, env):
        """The dialog sends the descriptions as edited, they replace what was stored."""
        client, jobs, gestartet, _ = _mit_folien(env)
        from src.features.praesentation import store
        from src.features.praesentation.schemas import ImageSpec
        folien = store.load_slides(7, UUID)
        folien[1].images = [ImageSpec(prompt="alt eins"), ImageSpec(prompt="alt zwei")]
        store.save_slides(7, UUID, folien)
        store.save_user_slides(7, UUID, folien)
        antwort = client.post(f"/praesentation/{UUID}/slides/s2/image",
                              json={"prompts": ["neu eins", "neu zwei"]})
        assert antwort.status_code == 200
        gespeichert = store.load_slides(7, UUID)
        assert [i.prompt for i in gespeichert[1].images] == ["neu eins", "neu zwei"]

    def test_regen_folie_liefert_inhalt_ohne_zu_speichern(self, env, monkeypatch):
        client, jobs, gestartet, ablage = _mit_folien(env)
        import src.routes.praesentation.slides as slides_route
        monkeypatch.setattr(slides_route, "llm_antwort", lambda n, anbieter=None: json.dumps({"slides": [
            {"id": "s2", "title": "Neu", "body": {"kind": "bullets", "items": ["x"]}}]}))
        antwort = client.post(f"/praesentation/{UUID}/slides/s2/regen", json={"messages": [], "selected_text": ""})
        assert antwort.json()["title"] == "Neu" and antwort.json()["layout"] == 3
        assert json.loads(ablage.get_job_file(7, UUID, "slides.json"))[1]["title"] == "T1"

    def test_finalize_und_download(self, env):
        client, jobs, gestartet, ablage = _mit_folien(env)
        assert client.post(f"/praesentation/{UUID}/finalize").status_code == 200
        assert gestartet[-1] == ("build", [UUID, 7, "de", 1, 0, None, True])
        jobs[UUID]["status"] = "success"
        antwort = client.get(f"/praesentation/{UUID}/download")
        assert antwort.status_code == 200 and antwort.content == b"PKdeck"
        assert 'filename="Deck.pptx"' in antwort.headers["content-disposition"]

    def test_vorschau_bild(self, env):
        client, jobs, gestartet, ablage = _mit_folien(env)
        from src.features.praesentation import store
        store.save_preview(7, UUID, "s2", b"png")
        antwort = client.get(f"/praesentation/{UUID}/preview/s2.png")
        assert antwort.status_code == 200 and antwort.headers["content-type"] == "image/png"
        assert client.get(f"/praesentation/{UUID}/preview/s9.png").status_code == 404

    def test_bilder_kommen_einzeln_und_verkleinert(self, env):
        """The live sketch shows each drawn picture as soon as it is stored, small enough for a card."""
        import io

        from PIL import Image

        client, jobs, gestartet, ablage = _mit_folien(env)
        from src.features.praesentation import store
        from src.features.praesentation.schemas import ImageSpec
        folien = store.load_slides(7, UUID)
        folien[1].images = [ImageSpec(prompt="eins"), ImageSpec(prompt="zwei")]
        store.save_user_slides(7, UUID, folien)
        roh = io.BytesIO()
        Image.new("RGB", (1600, 900), "red").save(roh, "PNG")
        store.save_image(7, UUID, "s2", 0, roh.getvalue())

        ansicht = client.get(f"/praesentation/{UUID}").json()
        assert ansicht["images"]["s2"] == ["0"]
        assert ansicht["images"]["s3"] == []
        assert ansicht["missing_images"] == ["s2"]

        antwort = client.get(f"/praesentation/{UUID}/image/s2/0")
        assert antwort.status_code == 200 and antwort.headers["content-type"] == "image/jpeg"
        assert Image.open(io.BytesIO(antwort.content)).size == (640, 360)
        assert client.get(f"/praesentation/{UUID}/image/s2/1").status_code == 404
        assert client.get(f"/praesentation/{UUID}/image/s2/x1").status_code == 404
        assert client.get(f"/praesentation/{UUID}/image/s2x/0").status_code == 404

    def test_vorschau_lehnt_einen_unfoermigen_folien_id_ab(self, env, monkeypatch):
        """A slide id that never matches the store's naming must not even reach storage."""
        client, jobs, gestartet, ablage = _mit_folien(env)
        from src.features.praesentation import store
        aufgerufen = []
        monkeypatch.setattr(store, "get_preview", lambda *a, **k: aufgerufen.append(a) or None)
        assert client.get(f"/praesentation/{UUID}/preview/s1x.png").status_code == 404
        assert aufgerufen == []

    def test_download_erst_nach_fertigstellen(self, env):
        """A first build already produces a deck.pptx, the download must wait for "Fertigstellen"."""
        client, jobs, gestartet, ablage = _mit_folien(env)
        assert jobs[UUID]["status"] == "awaiting_user"
        assert client.get(f"/praesentation/{UUID}/download").status_code == 404


class TestVorlagen:
    def test_hochladen_und_liste(self, env):
        client, _, _, _, vorlagen = env
        antwort = client.post("/praesentation/vorlagen", data={"name": "Meine", "stiltext": "S"},
                              files={"file": ("v.pptx", THL, "application/octet-stream")})
        assert antwort.status_code == 200
        assert antwort.json()["roles"] == ["abschnitt", "text", "text_mit_bild", "zwei_spalten"] and antwort.json()["hasImages"]
        liste = client.get("/praesentation/vorlagen").json()
        assert liste[0]["id"] == "thl" and liste[0]["system"] and liste[1]["name"] == "Meine"
        assert liste[1]["roles"] == ["text"]

    def test_makros_werden_abgewiesen(self, env):
        client, *_ = env
        import zipfile
        from io import BytesIO
        out = BytesIO()
        with zipfile.ZipFile(BytesIO(THL)) as src, zipfile.ZipFile(out, "w") as dst:
            for n in src.namelist():
                dst.writestr(n, src.read(n))
            dst.writestr("ppt/vbaProject.bin", b"x")
        antwort = client.post("/praesentation/vorlagen", data={"name": "M", "stiltext": ""},
                              files={"file": ("v.pptx", out.getvalue(), "application/octet-stream")})
        assert antwort.status_code == 422

    def test_elfte_wird_abgewiesen(self, env):
        client, _, _, _, vorlagen = env
        for i in range(10):
            vorlagen[f"v{i}"] = {"id": f"v{i}", "name": "x", "stiltext": ""}
        antwort = client.post("/praesentation/vorlagen", data={"name": "M", "stiltext": ""},
                              files={"file": ("v.pptx", THL, "application/octet-stream")})
        assert antwort.status_code == 422

    def test_loeschen(self, env):
        client, _, _, _, vorlagen = env
        vorlagen["v1"] = {"id": "v1", "name": "x", "stiltext": ""}
        assert client.delete("/praesentation/vorlagen/v1").status_code == 200
        assert client.delete("/praesentation/vorlagen/v1").status_code == 404
