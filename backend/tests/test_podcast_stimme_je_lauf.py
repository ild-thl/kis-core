"""Rendering fixes provider and voices once per run, never mid-run. If the chosen provider is down at start, the admin fallback speaks the whole podcast and only a new run decides anew (27.09.2026)."""

from contextlib import contextmanager

import pytest

from src.features.podcast import store
from src.features.podcast.schemas import Line, PodcastParams, Person
from src.services import tts_job_provider
from src.services.tts_job_provider import VoicePick
from src.tasks.podcast_tasks import _render

UID = 7
JOB = "f" * 32

ANBIETER = {
    3: {"id": 3, "name": "Lokal", "voices": [{"voice_id": "anna", "name": "Anna"},
                                           {"voice_id": "ben", "name": "Ben"}]},
    4: {"id": 4, "name": "Lokal", "voices": [{"voice_id": "carl", "name": "Carl"}]},
    21: {"id": 21, "name": "THL myLab", "voices": [{"voice_id": "onyx", "name": "Onyx"},
                                                    {"voice_id": "echo", "name": "Echo"},
                                                    {"voice_id": "nova", "name": "Nova"}]},
}
# How the fallback maps the voices when the chosen provider is missing at start.
ERSATZ = {"anna": "onyx", "ben": "echo", "carl": "onyx", "nova": "nova"}

LENA = Person(name="Lena", voice_id="anna", provider_id=3)
JONAS = Person(name="Jonas", voice_id="ben", provider_id=3)


class _Db:
    def __init__(self):
        self.status = []

    def update_job_status(self, job_uuid, status, progress=None, error_message=None):
        self.status.append((status, progress))

    def reset_job_to_awaiting(self, job_uuid):
        self.status.append(("awaiting_user", None))

    def get_job(self, job_uuid):
        return {"progress": None}


class _Uhr:
    """A stage clock that expires either at once or never."""

    def __init__(self, vorbei: bool):
        self.vorbei = vorbei

    def over(self) -> bool:
        return self.vorbei

    def spent(self) -> float:
        return 0.0


@pytest.fixture
def lauf(monkeypatch, lokal):
    """Real job folder on disk; only providers, database and assembly are faked."""
    stand = {"unten": set(), "wahl": [], "gesprochen": [], "zahlen": {}, "meta": {}, "anbieter": []}
    monkeypatch.setattr(_render, "db", _Db())
    monkeypatch.setattr("src.database.get_provider", lambda pid: ANBIETER.get(pid))
    monkeypatch.setattr(_render, "assert_not_cancelled", lambda job: None)
    monkeypatch.setattr(_render, "still_mine", lambda job, token: True)
    monkeypatch.setattr(_render, "attempt_failed", lambda job, meldung, **k: "waiting_retry")
    monkeypatch.setattr(_render, "continue_stage", lambda selbst, args, job: None)
    # The client is just the provider id, so the speaker is visible.
    monkeypatch.setattr(_render, "tts_client", lambda pid, user_id=None: pid)

    def vertonen(client, text, voice_id, sprache, tempo, *rest):
        stand["gesprochen"].append((client, voice_id))
        return f"{client}/{voice_id}".encode()

    monkeypatch.setattr(_render, "_mit_wiederholung", vertonen)
    monkeypatch.setattr(_render, "anbieter_und_modelle",
                        lambda pids, art: stand["anbieter"].extend(pids) or {})

    @contextmanager
    def messe(uid, job, phase):
        stand["zahlen"][phase] = {}
        yield stand["zahlen"][phase]

    @contextmanager
    def still(job):
        yield

    monkeypatch.setattr(_render, "messe", messe)
    monkeypatch.setattr(_render, "job_heartbeat", still)
    monkeypatch.setattr(_render, "montage",
                        type("M", (), {"kleben": staticmethod(lambda s, j: (b"mp3", 12.0))}))
    monkeypatch.setattr(_render, "save_result_file", lambda uid, job, endung, daten: "p.mp3")
    monkeypatch.setattr(_render, "save_result_meta", lambda uid, job, meta: stand["meta"].update(meta))
    monkeypatch.setattr(_render, "load_result_meta", lambda uid, job: {})
    monkeypatch.setattr(_render, "save_result_and_evict", lambda uid, job, pfad, name: None)

    def pick(pid, vids, taken=()):
        stand["wahl"].append((pid, list(vids)))
        if pid in stand["unten"]:
            return VoicePick(21, tuple(ERSATZ[v] for v in vids), True)
        return VoicePick(pid, tuple(vids), False)

    monkeypatch.setattr(tts_job_provider, "pick", pick)
    return stand


def _auftrag(personen, texte=("Eins.", "Zwei."), **kw) -> PodcastParams:
    params = PodcastParams(persons=personen, speed=1.0, provider_id=personen[0].provider_id, **kw)
    store.save_params(UID, JOB, params)
    store.save_user_script(UID, JOB, [Line(id=f"b{i}", speaker=i % len(personen), text=t)
                                      for i, t in enumerate(texte)])
    return params


def test_beim_start_spricht_der_ganze_podcast_mit_dem_rueckfall(lauf):
    _auftrag([LENA, JONAS])
    lauf["unten"].add(3)

    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    assert sorted(lauf["gesprochen"]) == [(21, "echo"), (21, "onyx")]


def test_ist_der_gewaehlte_da_bleibt_alles_wie_gewaehlt(lauf):
    _auftrag([LENA, JONAS])

    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    assert sorted(lauf["gesprochen"]) == [(3, "anna"), (3, "ben")]


@pytest.mark.parametrize("etappe, versuch", [(2, 0), (1, 1), (1, 0)])
def test_etappen_und_wiederanlaeufe_wechseln_nicht_zurueck(lauf, monkeypatch, etappe, versuch):
    """The first stage decides and produces nothing, then the chosen provider is back."""
    _auftrag([LENA, JONAS])
    lauf["unten"].add(3)
    monkeypatch.setattr(_render, "StageClock", lambda *a, **k: _Uhr(True))
    _render.run_podcast_render(JOB, UID, "de", 1, 0)
    assert lauf["gesprochen"] == []

    lauf["unten"].clear()
    monkeypatch.setattr(_render, "StageClock", lambda *a, **k: _Uhr(False))
    _render.run_podcast_render(JOB, UID, "de", etappe, versuch)

    assert sorted(lauf["gesprochen"]) == [(21, "echo"), (21, "onyx")]
    assert len(lauf["wahl"]) == 1, "nur der Start eines Laufs entscheidet"


def test_personen_eines_anbieters_werden_gemeinsam_entschieden(lauf):
    carl = Person(name="Carl", voice_id="carl", provider_id=4)
    _auftrag([LENA, JONAS, carl], texte=("Eins.", "Zwei.", "Drei."))

    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    assert sorted(lauf["wahl"]) == [(3, ["anna", "ben"]), (4, ["carl"])]


def test_ton_des_gewaehlten_wird_im_neuen_lauf_mit_rueckfall_neu_gesprochen(lauf):
    """Same text and voice id but another provider: the old audio must not stay."""
    _auftrag([Person(name="Lena", voice_id="nova", provider_id=3)], texte=("Eins.",))
    _render.run_podcast_render(JOB, UID, "de", 1, 0)
    assert lauf["gesprochen"] == [(3, "nova")]

    # How the page starts a new run, now the chosen provider is missing.
    store.delete_pin(UID, JOB)
    lauf["unten"].add(3)
    lauf["gesprochen"].clear()
    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    assert lauf["gesprochen"] == [(21, "nova")]
    assert store.get_line_audio(UID, JOB, "b0") == b"21/nova"


def test_ton_des_rueckfalls_wird_im_neuen_lauf_mit_dem_gewaehlten_ersetzt(lauf):
    _auftrag([LENA])
    lauf["unten"].add(3)
    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    store.delete_pin(UID, JOB)
    lauf["unten"].clear()
    lauf["gesprochen"].clear()
    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    assert sorted(lauf["gesprochen"]) == [(3, "anna"), (3, "anna")]


def test_unveraenderter_ton_desselben_anbieters_bleibt(lauf):
    _auftrag([LENA])
    lauf["unten"].add(3)
    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    store.delete_pin(UID, JOB)
    lauf["gesprochen"].clear()
    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    assert lauf["gesprochen"] == []


def test_zahlen_und_ergebnis_nennen_was_wirklich_sprach(lauf):
    _auftrag([LENA, JONAS], voice_label="Anna, Ben")
    lauf["unten"].add(3)

    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    vertonung = lauf["zahlen"]["vertonung"]
    assert vertonung["besetzung"] == "Lena (host, onyx, THL myLab), Jonas (host, echo, THL myLab)"
    assert vertonung["stimmen"] == 2
    assert set(lauf["anbieter"]) == {21}
    assert lauf["meta"]["voice_label"] == "Onyx, Echo"


def test_ohne_rueckfall_bleibt_das_stimmen_etikett_der_seite(lauf):
    _auftrag([LENA, JONAS], voice_label="Anna, Ben")

    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    assert lauf["meta"]["voice_label"] == "Anna, Ben"
    assert lauf["zahlen"]["vertonung"]["besetzung"] == "Lena (host, anna, Lokal), Jonas (host, ben, Lokal)"


def test_die_seite_zaehlt_den_ton_des_festgelegten_anbieters_als_vertont(lauf, monkeypatch):
    import src.routes.podcast.script as script_route

    _auftrag([LENA])
    lauf["unten"].add(3)
    _render.run_podcast_render(JOB, UID, "de", 1, 0)
    monkeypatch.setattr(script_route, "own_job", lambda uuid, user, locale: {
        "user_id": UID, "status": "success", "progress": None, "error_message": None, "result_path": "p"})

    antwort = script_route.get_podcast(JOB, {"user_id": UID}, "de")

    assert antwort["voiced"] == ["b0", "b1"]



def test_die_seite_zaehlt_ton_mit_eigenem_tempo_als_vertont(lauf, monkeypatch):
    """The page always compared with speed 1.0, so at 1.2 nothing counted as rendered."""
    import src.routes.podcast.script as script_route

    params = _auftrag([LENA])
    store.save_params(UID, JOB, params.model_copy(update={"speed": 1.2}))
    _render.run_podcast_render(JOB, UID, "de", 1, 0)
    monkeypatch.setattr(script_route, "own_job", lambda uuid, user, locale: {
        "user_id": UID, "status": "success", "progress": None, "error_message": None, "result_path": "p"})

    assert script_route.get_podcast(JOB, {"user_id": UID}, "de")["voiced"] == ["b0", "b1"]


def _vor_der_festlegung_vertont():
    """A podcast rendered before 28.09.2026: the provider is missing from the fingerprint."""
    _auftrag([LENA])
    store.save_voiced(UID, JOB, {"b0": {"text": "Eins.", "voice_id": "anna", "speed": 1.0},
                                 "b1": {"text": "Zwei.", "voice_id": "anna", "speed": 1.0}})
    for zeile in ("b0", "b1"):
        store.save_line_audio(UID, JOB, zeile, b"alt")


def test_alter_ton_des_gewaehlten_bleibt_ohne_anbieter_im_fingerabdruck(lauf):
    _vor_der_festlegung_vertont()

    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    assert lauf["gesprochen"] == []


def test_alter_ton_wird_neu_gesprochen_wenn_der_rueckfall_spricht(lauf):
    _vor_der_festlegung_vertont()
    lauf["unten"].add(3)

    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    assert lauf["gesprochen"] == [(21, "onyx"), (21, "onyx")]


def test_die_seite_zaehlt_alten_ton_des_gewaehlten_als_vertont(lauf, monkeypatch):
    import src.routes.podcast.script as script_route

    _vor_der_festlegung_vertont()
    monkeypatch.setattr(script_route, "own_job", lambda uuid, user, locale: {
        "user_id": UID, "status": "success", "progress": None, "error_message": None, "result_path": "p"})

    assert script_route.get_podcast(JOB, {"user_id": UID}, "de")["voiced"] == ["b0", "b1"]


def _starte_ueber_die_seite(monkeypatch, status: str) -> list:
    """Starts rendering like the page button and records the decision made on enqueue."""
    import src.routes.podcast.render as render_route
    import src.tasks.podcast_tasks as tasks
    import src.tasks.podcast_tasks._shared as shared

    monkeypatch.setattr(render_route, "own_job",
                        lambda uuid, user, locale: {"user_id": UID, "status": status})
    for name in ("enforce_open_jobs", "enforce_tool_burst", "enforce_quota"):
        monkeypatch.setattr(render_route, name, lambda *a, **k: None)
    for name in ("reset_attempts", "update_job_status", "set_job_celery_task_id"):
        monkeypatch.setattr(render_route.db, name, lambda *a, **k: None)
    monkeypatch.setattr(shared, "clear_cancel", lambda job: None)
    beim_start = []
    monkeypatch.setattr(tasks.run_podcast_render, "apply_async", lambda args=None, **k: (
        beim_start.append(store.load_pin(UID, JOB)), type("T", (), {"id": "t"})())[1])

    render_route.start_render(JOB, {"user_id": UID, "role": "staff"}, "de")
    return beim_start


# A fixed run in which Lena and Jonas speak with the fallback.
FESTGELEGT = {"voices": {"3/anna": {"provider_id": 21, "voice_id": "onyx"},
                         "3/ben": {"provider_id": 21, "voice_id": "echo"}}, "fallback": True}


@pytest.mark.parametrize("status", ["success", "awaiting_user"])
def test_ein_neuer_lauf_entscheidet_neu(lokal, monkeypatch, status):
    _auftrag([LENA, JONAS])
    store.save_pin(UID, JOB, FESTGELEGT)

    assert _starte_ueber_die_seite(monkeypatch, status) == [None]


@pytest.mark.parametrize("status", ["failed", "paused"])
def test_fortsetzen_behaelt_die_festlegung_des_laufs(lokal, monkeypatch, status):
    _auftrag([LENA, JONAS])
    store.save_pin(UID, JOB, FESTGELEGT)

    assert _starte_ueber_die_seite(monkeypatch, status) == [FESTGELEGT]


@pytest.mark.parametrize("status", ["failed", "paused"])
def test_fortsetzen_mit_geaenderter_besetzung_entscheidet_neu(lokal, monkeypatch, status):
    """A new voice has no place in the old run, so a new one starts."""
    _auftrag([LENA, Person(name="Carl", voice_id="carl", provider_id=4)])
    store.save_pin(UID, JOB, FESTGELEGT)

    assert _starte_ueber_die_seite(monkeypatch, status) == [None]


def test_fortsetzen_nach_fehler_spricht_mit_dem_rueckfall_weiter(lauf, monkeypatch):
    """The first stage fixes the fallback, then the job fails and is resumed."""
    _auftrag([LENA, JONAS])
    lauf["unten"].add(3)
    monkeypatch.setattr(_render, "StageClock", lambda *a, **k: _Uhr(True))
    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    lauf["unten"].clear()
    _starte_ueber_die_seite(monkeypatch, "failed")
    monkeypatch.setattr(_render, "StageClock", lambda *a, **k: _Uhr(False))
    _render.run_podcast_render(JOB, UID, "de", 1, 0)

    assert sorted(lauf["gesprochen"]) == [(21, "echo"), (21, "onyx")]
    assert len(lauf["wahl"]) == 1


@pytest.fixture
def echte_wahl(monkeypatch):
    """The real provider choice; only database and reachability are faked."""
    unten: set[int] = set()
    anbieter = {pid: {**a, "enabled": True, "protocol": "openai_compat", "capabilities": ["tts"]}
                for pid, a in ANBIETER.items()}
    monkeypatch.setattr("src.database.get_provider", lambda pid: anbieter.get(pid))
    monkeypatch.setattr("src.database.get_route", lambda art: {
        "fallback_provider_id": 21, "provider_models": {"21": "tts-1"}})
    monkeypatch.setattr(tts_job_provider, "_marked_down", lambda pid: pid in unten)
    monkeypatch.setattr(tts_job_provider, "_reachable", lambda provider: True)
    return unten


def test_zwei_anbieter_im_rueckfall_sprechen_nie_mit_derselben_stimme(echte_wahl):
    carl = Person(name="Carl", voice_id="carl", provider_id=4)
    echte_wahl.update({3, 4})

    pin = _render._festlegen(PodcastParams(persons=[LENA, carl], provider_id=3))

    lena, carl = store.pinned_voice(pin, 3, "anna"), store.pinned_voice(pin, 4, "carl")
    assert lena[0] == carl[0] == 21
    assert lena != carl


@pytest.mark.parametrize("nora_zuerst", [True, False])
def test_der_rueckfall_meidet_die_stimme_einer_person_die_dort_bleibt(echte_wahl, nora_zuerst):
    nora = Person(name="Nora", voice_id="onyx", provider_id=21)
    echte_wahl.add(3)
    personen = [nora, LENA] if nora_zuerst else [LENA, nora]

    pin = _render._festlegen(PodcastParams(persons=personen, provider_id=21))

    assert store.pinned_voice(pin, 21, "onyx") == (21, "onyx")
    assert store.pinned_voice(pin, 3, "anna") == (21, "echo")


def test_gleiche_stimmkennung_bei_einem_anderen_anbieter_zaehlt_nicht(echte_wahl):
    """Nova at another provider speaks there, the fallback keeps its own Nova."""
    lena = Person(name="Lena", voice_id="nova", provider_id=3)
    max_ = Person(name="Max", voice_id="nova", provider_id=4)
    echte_wahl.add(3)

    pin = _render._festlegen(PodcastParams(persons=[max_, lena], provider_id=4))

    assert store.pinned_voice(pin, 3, "nova") == (21, "nova")
    assert store.pinned_voice(pin, 4, "nova") == (4, "nova")


class _S3Fehler(Exception):
    """How S3 reports an error, with the code in the response."""

    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


def test_ein_lesefehler_der_festlegung_laesst_die_etappe_scheitern_statt_neu_zu_waehlen(lauf, monkeypatch):
    _auftrag([LENA, JONAS])
    store.save_pin(UID, JOB, FESTGELEGT)
    echt = store.get_job_file

    def lesen(uid, job, name):
        if name == store.PIN_FILE:
            raise _S3Fehler("503")
        return echt(uid, job, name)

    monkeypatch.setattr(store, "get_job_file", lesen)
    with pytest.raises(_S3Fehler):
        _render.run_podcast_render(JOB, UID, "de", 2, 0)

    monkeypatch.setattr(store, "get_job_file", echt)
    assert lauf["wahl"] == [] and lauf["gesprochen"] == []
    assert store.load_pin(UID, JOB) == FESTGELEGT


class TestAblage:
    def test_anderer_anbieter_mit_gleicher_stimmkennung_braucht_neuen_ton(self):
        line = Line(id="b0", speaker=0, text="Ein Satz.")
        vertont = {"b0": store.fingerprint(line, "nova", 1.0, 3)}
        assert store.needs_voice(line, vertont, "nova", 1.0, 21) is True
        assert store.needs_voice(line, vertont, "nova", 1.0, 3) is False

    def test_ohne_festlegung_gilt_die_gewaehlte_stimme(self):
        assert store.pinned_voice(None, 3, "anna") == (3, "anna")

    def test_die_festlegung_ueberlebt_den_ordner_und_verschwindet_beim_loeschen(self, lokal):
        store.save_pin(UID, JOB, {"voices": {}, "fallback": False})
        assert store.load_pin(UID, JOB) == {"voices": {}, "fallback": False}
        store.delete_pin(UID, JOB)
        assert store.load_pin(UID, JOB) is None
        # Deleting without a decision is not an error.
        store.delete_pin(UID, JOB)

    @pytest.mark.parametrize("code", ["404", "NoSuchKey"])
    def test_eine_fehlende_festlegung_in_s3_ist_keine(self, monkeypatch, code):
        monkeypatch.setattr(store, "get_job_file", lambda *a: (_ for _ in ()).throw(_S3Fehler(code)))
        assert store.load_pin(UID, JOB) is None

    @pytest.mark.parametrize("fehler", [_S3Fehler("503"), _S3Fehler("AccessDenied"), ConnectionError("weg")])
    def test_ein_anderer_lesefehler_ist_keine_fehlende_festlegung(self, monkeypatch, fehler):
        monkeypatch.setattr(store, "get_job_file", lambda *a: (_ for _ in ()).throw(fehler))
        with pytest.raises(type(fehler)):
            store.load_pin(UID, JOB)
