"""The guards of the podcast routes: what is refused before a job ever exists."""

import json

import pytest
from fastapi.testclient import TestClient

from src.permissions import Permissions


def _out_of_local_mode(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")


class FakeAblage:
    """The job folder in memory, keyed the way the real one is."""

    def __init__(self):
        self.dateien: dict[tuple[int, str, str], bytes] = {}

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


UUID = "a" * 32


@pytest.fixture
def env(monkeypatch):
    _out_of_local_mode(monkeypatch)
    from src.app import app
    from src.dependencies import get_current_user, get_settings
    from src.dependencies_rbac import get_user_permissions
    from src.features.podcast import store
    from src.security.auth import verify_auth

    from src.services import job_files

    ablage = FakeAblage()
    # The shared sources go through job_files, not the tool's store.
    for modul in (store, job_files):
        for name in ("save_job_file", "get_job_file", "job_file_exists"):
            monkeypatch.setattr(modul, name, getattr(ablage, name))
    monkeypatch.setattr(store, "delete_job_file", ablage.delete_job_file)
    monkeypatch.setattr("src.dependencies_rbac.is_released_now", lambda key: True)

    jobs: dict[str, dict] = {}
    import src.routes.podcast.render as render_route
    import src.routes.podcast.start as start_route
    import src.routes._shared as shared

    monkeypatch.setattr(shared.db, "get_job", lambda uuid: jobs.get(uuid))
    monkeypatch.setattr(start_route.db, "count_all_jobs_for_tool", lambda uid, tools: 0)
    monkeypatch.setattr(start_route.db, "create_job", lambda *a, **k: None)
    monkeypatch.setattr(start_route.db, "set_job_celery_task_id", lambda *a, **k: None)
    monkeypatch.setattr(start_route.db, "update_job_status", lambda *a, **k: None)
    monkeypatch.setattr(start_route, "enforce_tool_burst", lambda *a, **k: None)
    monkeypatch.setattr(start_route, "enforce_quota", lambda *a, **k: None)
    monkeypatch.setattr(render_route, "enforce_tool_burst", lambda *a, **k: None)
    monkeypatch.setattr(render_route, "enforce_quota", lambda *a, **k: None)
    monkeypatch.setattr(render_route.db, "set_job_celery_task_id", lambda *a, **k: None)
    monkeypatch.setattr(render_route.db, "update_job_status", lambda *a, **k: None)

    # An upload must not create anything; anything firing here means exactly that is broken.
    ablage.angelegt = []
    monkeypatch.setattr(start_route.db, "create_aia_source",
                        lambda **kw: ablage.angelegt.append(kw.get("filename")))

    gestartet: list[str] = []

    class FakeTask:
        id = "task-1"

    import src.tasks.podcast_tasks as tasks

    monkeypatch.setattr(tasks.run_podcast_script, "apply_async",
                        lambda args=None, **k: (gestartet.append("script"), FakeTask())[1])
    monkeypatch.setattr(tasks.run_podcast_render, "apply_async",
                        lambda args=None, **k: (gestartet.append("render"), FakeTask())[1])

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 7, "email": "a@th-luebeck.de", "role": "staff"}
    app.dependency_overrides[get_user_permissions] = lambda: Permissions(keys=frozenset({"tools.podcast"}))
    yield TestClient(app), jobs, gestartet, ablage
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _params(**kw):
    grund = {
        "language": "de",
        "instructions": "",
        "persons": [{"name": "Lena", "role": "host", "voice_id": "anna", "provider_id": 3},
                    {"name": "Jonas", "role": "expert", "voice_id": "ben", "provider_id": 3}],
        "length": "medium",
        "style": "teaching",
    }
    grund.update(kw)
    return json.dumps(grund)




class TestKiAnbieter:
    def test_ein_nicht_waehlbarer_anbieter_wird_abgewiesen(self, env, monkeypatch):
        import src.routes.podcast.start as start_route

        client, *_ = env
        monkeypatch.setattr(start_route.feature_provider_choices, "is_eligible", lambda f, pid: False)
        antwort = client.post("/podcast/start", data={"params": _params(llm_provider_id=99), "mode": "blank"})
        assert antwort.status_code == 400

    def test_der_gewaehlte_anbieter_reist_in_den_einstellungen_mit(self, env, monkeypatch):
        import src.routes.podcast.start as start_route

        client, *_ = env
        gespeichert = []
        monkeypatch.setattr(start_route.feature_provider_choices, "is_eligible", lambda f, pid: pid == 21)
        monkeypatch.setattr(start_route.store, "save_params",
                            lambda uid, job, params: gespeichert.append(params))
        antwort = client.post("/podcast/start", data={"params": _params(llm_provider_id=21), "mode": "blank"})
        assert antwort.status_code == 200
        assert gespeichert[0].llm_provider_id == 21


class TestSkriptUndVertonung:
    def _job(self, jobs, status="awaiting_user"):
        jobs[UUID] = {"job_uuid": UUID, "user_id": 7, "tool": "podcast", "status": status,
                      "progress": None, "error_message": None, "result_path": None}

    def test_speichert_das_geprueefte_skript_mit_echten_ids(self, env):
        client, jobs, _g, _a = env
        self._job(jobs)
        antwort = client.put(f"/podcast/{UUID}/script", json={"lines": [
            {"id": "", "speaker": 0, "text": "Eins."},
            {"id": "neu3", "speaker": 1, "text": "Zwei."},
        ]})
        assert antwort.status_code == 200
        assert [l["id"] for l in antwort.json()["lines"]] == ["b0", "b1"]

    def test_behaelt_einen_noch_leeren_beitrag(self, env):
        """A freshly added line is empty, saving must not drop it."""
        client, jobs, _g, _a = env
        self._job(jobs)
        antwort = client.put(f"/podcast/{UUID}/script", json={"lines": [
            {"id": "b0", "speaker": 0, "text": "Eins."},
            {"id": "b1", "speaker": 0, "text": "   "},
        ]})
        assert [l["text"] for l in antwort.json()["lines"]] == ["Eins.", ""]

    def test_weist_ein_skript_ganz_ohne_zeilen_ab(self, env):
        client, jobs, _g, _a = env
        self._job(jobs)
        assert client.put(f"/podcast/{UUID}/script", json={"lines": []}).status_code == 422

    def test_weist_zu_viele_beitraege_mit_meldung_ab(self, env):
        """The 251st line used to vanish silently, now the UI says so."""
        from src.limits import PODCAST_MAX_LINES

        client, jobs, _g, _a = env
        self._job(jobs)
        zeilen = [{"id": "", "speaker": 0, "text": "Text."} for _ in range(PODCAST_MAX_LINES + 1)]
        antwort = client.put(f"/podcast/{UUID}/script", json={"lines": zeilen})
        assert antwort.status_code == 422
        assert str(PODCAST_MAX_LINES) in antwort.json()["detail"]

    def test_nimmt_genau_die_erlaubte_zahl_an_beitraegen(self, env):
        from src.limits import PODCAST_MAX_LINES

        client, jobs, _g, _a = env
        self._job(jobs)
        zeilen = [{"id": "", "speaker": 0, "text": "Text."} for _ in range(PODCAST_MAX_LINES)]
        assert client.put(f"/podcast/{UUID}/script", json={"lines": zeilen}).status_code == 200

    def test_weist_ein_zu_langes_skript_ab(self, env):
        """Same character limit as text to speech, screencast and translation."""
        from src.limits import PODCAST_MAX_CHARS

        client, jobs, _g, _a = env
        self._job(jobs)
        zeilen = [{"id": "", "speaker": 0, "text": "x" * 1000} for _ in range(PODCAST_MAX_CHARS // 1000 + 1)]
        antwort = client.put(f"/podcast/{UUID}/script", json={"lines": zeilen})
        assert antwort.status_code == 422
        assert "100.000" in antwort.json()["detail"]

    def test_ein_angehaltener_auftrag_darf_wieder_starten(self, env):
        client, jobs, _g, _a = env
        self._job(jobs, status="paused")
        assert client.put(f"/podcast/{UUID}/script", json={"lines": [
            {"id": "b0", "speaker": 0, "text": "Eins."},
        ]}).status_code == 200

    def test_waehrend_des_wiederanlaufs_bleibt_das_skript_gesperrt(self, env):
        client, jobs, _g, _a = env
        self._job(jobs, status="waiting_retry")
        assert client.put(f"/podcast/{UUID}/script", json={"lines": [
            {"id": "b0", "speaker": 0, "text": "Eins."},
        ]}).status_code == 409

    def test_gibt_den_fortschritt_als_objekt_zurueck(self, env):
        """The database stores progress as text, the page needs an object."""
        client, jobs, _g, _a = env
        self._job(jobs, status="success")
        jobs[UUID]["progress"] = json.dumps({"step": "done", "fertig": [0, 1]})
        antwort = client.get(f"/podcast/{UUID}")
        assert antwort.status_code == 200
        assert antwort.json()["progress"] == {"step": "done", "fertig": [0, 1]}

    def test_vertraegt_einen_auftrag_ohne_fortschritt(self, env):
        client, jobs, _g, _a = env
        self._job(jobs)
        assert client.get(f"/podcast/{UUID}").json()["progress"] is None

    def test_laesst_das_skript_waehrend_der_arbeit_in_ruhe(self, env):
        client, jobs, _g, _a = env
        self._job(jobs, status="running")
        antwort = client.put(f"/podcast/{UUID}/script", json={"lines": [{"id": "b0", "speaker": 0, "text": "Eins."}]})
        assert antwort.status_code == 409

    def test_startet_die_vertonung_nur_mit_skript(self, env):
        client, jobs, gestartet, _a = env
        self._job(jobs)
        assert client.post(f"/podcast/{UUID}/render").status_code == 422
        client.put(f"/podcast/{UUID}/script", json={"lines": [{"id": "b0", "speaker": 0, "text": "Eins."}]})
        assert client.post(f"/podcast/{UUID}/render").status_code == 200
        assert gestartet == ["render"]

    def test_vertont_ein_skript_aus_lauter_leeren_beitraegen_nicht(self, env):
        client, jobs, gestartet, _a = env
        self._job(jobs)
        client.put(f"/podcast/{UUID}/script", json={"lines": [{"id": "b0", "speaker": 0, "text": ""}]})
        assert client.post(f"/podcast/{UUID}/render").status_code == 422
        assert gestartet == []

    def test_startet_keine_zweite_vertonung_waehrend_der_ersten(self, env):
        client, jobs, _g, _a = env
        self._job(jobs, status="running")
        assert client.post(f"/podcast/{UUID}/render").status_code == 409



class TestFremderAuftrag:
    def test_bleibt_fuer_ein_anderes_konto_unsichtbar(self, env):
        client, jobs, _g, _a = env
        jobs[UUID] = {"job_uuid": UUID, "user_id": 99, "tool": "podcast", "status": "awaiting_user",
                      "progress": None, "error_message": None, "result_path": None}
        assert client.get(f"/podcast/{UUID}").status_code == 404
        assert client.post(f"/podcast/{UUID}/render").status_code == 404

    def test_weist_einen_auftrag_eines_anderen_werkzeugs_ab(self, env):
        client, jobs, _g, _a = env
        jobs[UUID] = {"job_uuid": UUID, "user_id": 7, "tool": "tts", "status": "success",
                      "progress": None, "error_message": None, "result_path": None}
        assert client.get(f"/podcast/{UUID}").status_code == 404


class TestBesetzungAendern:
    """The cast after start: what is saved and what is rejected."""

    def _job(self, jobs, status="success"):
        jobs[UUID] = {"job_uuid": UUID, "user_id": 7, "tool": "podcast", "status": status,
                      "progress": None, "error_message": None, "result_path": None}

    def _vorher(self, personen=2):
        from src.features.podcast import store
        from src.features.podcast.schemas import Line, Person, PodcastParams

        alle = [Person(name="Lena", role="host", voice_id="anna", provider_id=3),
                Person(name="Jonas", role="expert", voice_id="ben", provider_id=3),
                Person(name="Amira", role="student", voice_id="cara", provider_id=3)]
        store.save_params(7, UUID, PodcastParams(language="de", instructions="Kurz halten.",
                                                 persons=alle[:personen], length="medium",
                                                 style="teaching", provider_id=3))
        if personen == 4:
            store.save_user_script(7, UUID, [Line(id=f"b{i}", speaker=i, text=f"Satz {i}.")
                                             for i in range(4)])
        else:
            store.save_user_script(7, UUID, [Line(id="b0", speaker=0, text="Eins."),
                                             Line(id="b1", speaker=personen - 1, text="Zwei.")])

    def _neu(self, **kw):
        grund = {
            "persons": [{"name": "Lena", "role": "host", "voice_id": "dora", "provider_id": 5}],
            "length": "medium",
            "style": "teaching",
        }
        grund.update(kw)
        return grund

    def test_speichert_die_neue_besetzung(self, env):
        client, jobs, _g, _a = env
        self._job(jobs)
        self._vorher()
        antwort = client.put(f"/podcast/{UUID}/params", json=self._neu())
        assert antwort.status_code == 200

        from src.features.podcast import store
        stand = store.load_params(7, UUID)
        assert [p.voice_id for p in stand.persons] == ["dora"]
        assert stand.provider_id == 5

    def test_speichert_das_neue_tempo(self, env):
        client, jobs, _g, _a = env
        self._job(jobs)
        self._vorher()
        assert client.put(f"/podcast/{UUID}/params", json=self._neu(speed=1.2)).status_code == 200

        from src.features.podcast import store
        assert store.load_params(7, UUID).speed == 1.2

    def test_behaelt_sprache_und_hinweise_des_starts(self, env):
        client, jobs, _g, _a = env
        self._job(jobs)
        self._vorher()
        client.put(f"/podcast/{UUID}/params", json=self._neu())

        from src.features.podcast import store
        stand = store.load_params(7, UUID)
        assert stand.language == "de"
        assert stand.instructions == "Kurz halten."

    def test_verteilt_beitraege_einer_entfernten_person_per_modulo(self, env):
        """Capping at 0 would give the whole rest of the conversation to one voice."""
        client, jobs, _g, _a = env
        self._job(jobs)
        self._vorher(personen=4)
        zwei = self._neu(persons=[
            {"name": "Lena", "role": "host", "voice_id": "dora", "provider_id": 5},
            {"name": "Jonas", "role": "expert", "voice_id": "emil", "provider_id": 5},
        ])
        assert client.put(f"/podcast/{UUID}/params", json=zwei).status_code == 200

        from src.features.podcast import store
        # Amira was 2 and becomes 0, Tom was 3 and becomes 1.
        assert [l.speaker for l in store.load_lines(7, UUID)] == [0, 1, 0, 1]

    def test_zieht_alles_auf_die_erste_person_wenn_nur_eine_bleibt(self, env):
        client, jobs, _g, _a = env
        self._job(jobs)
        self._vorher(personen=3)
        assert client.put(f"/podcast/{UUID}/params", json=self._neu()).status_code == 200

        from src.features.podcast import store
        assert [l.speaker for l in store.load_lines(7, UUID)] == [0, 0]

    def test_laesst_beitraege_in_ruhe_die_ihre_person_behalten(self, env):
        client, jobs, _g, _a = env
        self._job(jobs)
        self._vorher(personen=2)
        zwei = self._neu(persons=[
            {"name": "Lena", "role": "host", "voice_id": "dora", "provider_id": 5},
            {"name": "Jonas", "role": "expert", "voice_id": "emil", "provider_id": 5},
        ])
        assert client.put(f"/podcast/{UUID}/params", json=zwei).status_code == 200

        from src.features.podcast import store
        assert [l.speaker for l in store.load_lines(7, UUID)] == [0, 1]

    def test_laesst_die_besetzung_waehrend_der_arbeit_in_ruhe(self, env):
        client, jobs, _g, _a = env
        self._job(jobs, status="running")
        self._vorher()
        assert client.put(f"/podcast/{UUID}/params", json=self._neu()).status_code == 409

    def test_weist_eine_person_ohne_stimme_ab(self, env):
        client, jobs, _g, _a = env
        self._job(jobs)
        self._vorher()
        ohne = self._neu(persons=[{"name": "Lena", "role": "host", "voice_id": "", "provider_id": 5}])
        assert client.put(f"/podcast/{UUID}/params", json=ohne).status_code == 422

    def test_weist_fuenf_personen_ab(self, env):
        client, jobs, _g, _a = env
        self._job(jobs)
        self._vorher()
        viele = self._neu(persons=[{"name": f"P{i}", "role": "host", "voice_id": "v", "provider_id": 5}
                                   for i in range(5)])
        assert client.put(f"/podcast/{UUID}/params", json=viele).status_code == 422

    def test_weist_eine_leere_besetzung_ab(self, env):
        client, jobs, _g, _a = env
        self._job(jobs)
        self._vorher()
        assert client.put(f"/podcast/{UUID}/params", json=self._neu(persons=[])).status_code == 422

    def test_weist_einen_unbekannten_stil_ab(self, env):
        client, jobs, _g, _a = env
        self._job(jobs)
        self._vorher()
        assert client.put(f"/podcast/{UUID}/params", json=self._neu(style="rap")).status_code == 422

    def test_weist_einen_auftrag_ohne_einstellungen_ab(self, env):
        client, jobs, _g, _a = env
        self._job(jobs)
        assert client.put(f"/podcast/{UUID}/params", json=self._neu()).status_code == 404
