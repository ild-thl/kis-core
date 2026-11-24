"""What a result was made with stays next to it, beside the admin numbers."""

import pytest

from src.services import provider_transport
from src.services.job_statistik import angaben_merken, notiere
from src.storage import load_result_meta


UID = 7
JOB = "c" * 32


@pytest.fixture(autouse=True)
def _keine_aufzeichnung(monkeypatch):
    """Each test starts without a recording job and leaves none behind."""
    monkeypatch.setattr(provider_transport, "_answered", None)


def test_angaben_landen_in_der_meta(lokal):
    angaben_merken(UID, JOB, {"anbieter": "THL myLab", "ziel": "EN-US", "glossar": False})

    assert load_result_meta(UID, JOB)["angaben"] == {"anbieter": "THL myLab", "ziel": "EN-US", "glossar": False}


def test_leere_angaben_fallen_weg(lokal):
    angaben_merken(UID, JOB, {"anbieter": "", "stimme": None, "format": "srt"})

    assert load_result_meta(UID, JOB)["angaben"] == {"format": "srt"}


def test_zahlen_bleiben_erhalten(lokal):
    notiere(UID, JOB, "vertonung", {"folien": 3})
    angaben_merken(UID, JOB, {"anbieter": "Lokal"})

    meta = load_result_meta(UID, JOB)
    assert meta["stats"]["vertonung"] == {"folien": 3}
    assert meta["angaben"] == {"anbieter": "Lokal"}


def _tuer():
    from src.services.provider_transport import Target, _Door

    lokal = Target(provider_id=1, name="Lokal", root="http://lokal", api_key="k", model="m")
    mylab = Target(provider_id=2, name="THL myLab", root="http://mylab", api_key="k", model="m")
    return _Door(lokal, mylab, "llm"), lokal, mylab


def test_der_rueckfall_steht_als_anbieter_da():
    from src.services import provider_transport
    from src.services.job_statistik import wer_antwortete

    tuer, _, mylab = _tuer()
    provider_transport.record_answering()
    tuer.served(mylab)

    assert wer_antwortete("chat") == "THL myLab"


def test_wechsel_mitten_im_auftrag_nennt_beide():
    from src.services import provider_transport
    from src.services.job_statistik import wer_antwortete

    tuer, lokal, mylab = _tuer()
    provider_transport.record_answering()
    tuer.served(lokal)
    tuer.served(mylab)
    tuer.served(lokal)

    assert wer_antwortete("chat") == "Lokal, THL myLab"


def test_ohne_aufruf_durch_die_tuer_gilt_der_gewaehlte(monkeypatch):
    from src.services import job_statistik, provider_transport

    provider_transport.record_answering()
    monkeypatch.setattr(job_statistik, "route_kennung", lambda feature, pid=None: {"anbieter": "DeepL"})

    assert job_statistik.wer_antwortete("doc_translate", 5) == "DeepL"


def test_ein_neuer_auftrag_beginnt_leer():
    from src.services import provider_transport

    tuer, _, mylab = _tuer()
    provider_transport.record_answering()
    tuer.served(mylab)
    provider_transport.record_answering()

    assert provider_transport.answered() == []


def _job(tool: str, result_filename: str = "") -> dict:
    return {"user_id": UID, "job_uuid": JOB, "tool": tool, "result_filename": result_filename}


def test_alte_sprachausgabe_liest_ihre_einstellungen(lokal, monkeypatch):
    import json

    from src import dependencies
    from src.services import job_statistik
    from src.storage import save_job_file

    monkeypatch.setattr(job_statistik, "anbieter_name", lambda pid: "Lokal Audio DE")
    monkeypatch.setattr(dependencies, "_voice_language_for", lambda pid, vid: "de")
    save_job_file(UID, JOB, "tts_params.json", json.dumps({"provider_id": 3, "voice_id": "k", "voice_label": "Kerstin"}).encode())

    assert job_statistik.angaben_lesen(_job("tts")) == {"anbieter": "Lokal Audio DE", "sprache": "de", "stimme": "Kerstin"}


def test_gespeicherte_angaben_gehen_vor(lokal, monkeypatch):
    import json

    from src import dependencies
    from src.services import job_statistik
    from src.storage import save_job_file

    monkeypatch.setattr(job_statistik, "anbieter_name", lambda pid: "Lokal Audio DE")
    monkeypatch.setattr(dependencies, "_voice_language_for", lambda pid, vid: "de")
    save_job_file(UID, JOB, "tts_params.json", json.dumps({"provider_id": 3, "voice_id": "k", "voice_label": "Kerstin"}).encode())
    angaben_merken(UID, JOB, {"anbieter": "THL myLab", "stimme": "Alloy", "sprache": "en"})

    assert job_statistik.angaben_lesen(_job("tts")) == {"anbieter": "THL myLab", "stimme": "Alloy", "sprache": "en"}


def test_zusammenfassung_bringt_ihre_anweisung_mit(lokal):
    import json

    from src.features.summary.models import INSTRUCTIONS_FILE
    from src.services.job_statistik import angaben_lesen
    from src.storage import save_job_file

    save_job_file(UID, JOB, "summary_params.json", json.dumps({"template_slug": "zeitstrahl", "provider_id": None}).encode())
    save_job_file(UID, JOB, INSTRUCTIONS_FILE, "Höchstens eine Seite.\n".encode())

    assert angaben_lesen(_job("summary")) == {"vorlage": "zeitstrahl", "anweisung": "Höchstens eine Seite."}


def test_transkript_nennt_sein_format_aus_dem_dateinamen(lokal):
    from src.services.job_statistik import angaben_lesen

    assert angaben_lesen(_job("transcription", "vortrag.srt")) == {"format": "srt"}
    assert angaben_lesen(_job("transcription", "vortrag.txt")) == {"format": "text"}


def test_screencast_nennt_die_stimme_die_wirklich_sprach(lokal, monkeypatch):
    import json

    from src import dependencies
    from src.services import job_statistik
    from src.storage import save_job_file

    monkeypatch.setattr(job_statistik, "anbieter_name", lambda pid: {4: "THL myLab"}[pid])
    monkeypatch.setattr(dependencies, "_voice_language_for", lambda pid, vid: "en" if vid == "alloy" else "")
    save_job_file(UID, JOB, "render_params.json", json.dumps({"provider_id": 4, "voice_id": "alloy", "voice_label": "Alloy"}).encode())

    assert job_statistik.angaben_lesen(_job("screencast_translate")) == {"anbieter": "THL myLab", "sprache": "en", "stimme": "Alloy"}


def test_screencast_ohne_render_bleibt_leer(lokal):
    from src.services.job_statistik import angaben_lesen

    assert angaben_lesen(_job("screencast_translate")) == {}


def test_screencast_mit_allsprachiger_stimme_nennt_die_zielsprache(lokal, monkeypatch):
    import json

    from src import dependencies
    from src.services import job_statistik, tts_job_provider
    from src.storage import save_job_file, save_result_meta

    monkeypatch.setattr(job_statistik, "anbieter_name", lambda pid: "THL myLab")
    monkeypatch.setattr(dependencies, "_voice_language_for", lambda pid, vid: "")
    monkeypatch.setattr(tts_job_provider, "voice_name", lambda pid, vid: "Alloy")
    save_job_file(UID, JOB, "render_params.json", json.dumps({"provider_id": 4, "voice_id": "alloy", "voice_label": None}).encode())
    save_result_meta(UID, JOB, {"target_lang": "EN-US"})

    assert job_statistik.angaben_lesen(_job("screencast_translate")) == {"anbieter": "THL myLab", "sprache": "en", "stimme": "Alloy"}


def test_bilder_bringen_anbieter_prompt_und_einstellungen_mit(lokal):
    """User request 07.10.2026: images also get the info icon with provider, kind and prompt."""
    from src.services.job_statistik import angaben_lesen
    from src.storage import save_result_meta

    save_result_meta(UID, JOB, {"beschreibung": "Ein Apfel", "modell_prompt": "Foto. Ein Apfel", "stil": "foto",
                                "format": "16:9", "qualitaet": "hoch", "groesse": "1344x768", "anbieter": "Lokal"})

    assert angaben_lesen(_job("image_generate")) == {"anbieter": "Lokal", "stil": "foto", "format": "16:9",
                                                     "qualitaet": "hoch", "groesse": "1344x768", "prompt": "Ein Apfel"}


def test_eine_bildanalyse_nennt_aufgabe_und_frage(lokal):
    from src.services.job_statistik import angaben_lesen
    from src.storage import save_result_meta

    save_result_meta(UID, JOB, {"quelle": "", "titel": "Wie alt?", "aufgabe": "frage", "frage": "Wie alt?",
                                "vorlage": "vorlage.png", "dateiname": "a.png", "anbieter": "THL myLab"})

    assert angaben_lesen(_job("image_analyze")) == {"anbieter": "THL myLab", "aufgabe": "frage", "frage": "Wie alt?"}
