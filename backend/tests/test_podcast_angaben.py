"""The details next to the finished podcast: who speaks with which role and voice, at which provider."""

import pytest

from src.features.podcast import angaben as modul
from src.features.podcast import store
from src.features.podcast.schemas import Person, PodcastParams
from src.services import job_statistik


UID = 7
JOB = "c" * 32
ANBIETER = {1: {"name": "Lokal", "voices": [{"voice_id": "kerstin", "name": "Kerstin"}, {"voice_id": "thorsten", "name": "Thorsten"}]},
            2: {"name": "THL myLab", "voices": [{"voice_id": "nova", "name": "Nova"}]}}


@pytest.fixture(autouse=True)
def _anbieter(monkeypatch):
    monkeypatch.setattr(modul.db, "get_provider", lambda pid: ANBIETER.get(pid))
    monkeypatch.setattr("src.services.tts_job_provider.db.get_provider", lambda pid: ANBIETER.get(pid))


def _params() -> PodcastParams:
    return PodcastParams(language="de", source_label="Skript.pdf, Fallstudie.pdf", provider_id=1, persons=[
        Person(name="Lena", role="host", voice_id="kerstin", provider_id=1),
        Person(name="Jonas", role="expert", voice_id="thorsten", provider_id=1),
    ])


def test_besetzung_mit_rolle_und_stimmname():
    a = modul.angaben(_params(), None)

    assert a["anbieter"] == "Lokal"
    assert a["sprache"] == "de"
    assert a["material"] == "Skript.pdf, Fallstudie.pdf"
    assert a["besetzung"] == [{"name": "Lena", "rolle": "host", "stimme": "Kerstin"},
                              {"name": "Jonas", "rolle": "expert", "stimme": "Thorsten"}]


def test_der_rueckfall_nennt_wer_wirklich_sprach():
    pin = {"voices": {store.pin_key(1, "thorsten"): {"provider_id": 2, "voice_id": "nova"}}}

    a = modul.angaben(_params(), pin)

    assert a["anbieter"] == "Lokal, THL myLab"
    assert a["besetzung"][1] == {"name": "Jonas", "rolle": "expert", "stimme": "Nova"}


def test_alter_podcast_liest_seine_einstellungen(lokal):
    store.save_params(UID, JOB, _params())

    a = job_statistik.angaben_lesen({"user_id": UID, "job_uuid": JOB, "tool": "podcast"})

    assert a["besetzung"][0]["name"] == "Lena"
    assert a["anbieter"] == "Lokal"


def test_gespeicherte_angaben_gehen_vor(lokal):
    store.save_params(UID, JOB, _params())
    job_statistik.angaben_merken(UID, JOB, {"anbieter": "Gemini", "besetzung": []})

    a = job_statistik.angaben_lesen({"user_id": UID, "job_uuid": JOB, "tool": "podcast"})

    assert a == {"anbieter": "Gemini", "besetzung": []}


def test_anweisung_und_wer_das_skript_schrieb(lokal):
    params = _params()
    params.instructions = "Nur Kapitel 2"
    store.save_params(UID, JOB, params)
    job_statistik.notiere(UID, JOB, "skript", {"anbieter": "THL myLab", "modell": "m"})
    job_statistik.angaben_merken(UID, JOB, {"anbieter": "Lokal"})

    a = job_statistik.angaben_lesen({"user_id": UID, "job_uuid": JOB, "tool": "podcast"})

    assert a == {"anbieter": "Lokal", "anweisung": "Nur Kapitel 2", "textanbieter": "THL myLab"}
