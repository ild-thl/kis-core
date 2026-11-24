"""Voices get a fallback per job: the choice is made once at start, never mid-job.

User decision 27.09.2026: if the chosen provider is down at start the whole job runs with the admin fallback, otherwise entirely with the chosen one.
"""
import pytest

from src.services import tts_job_provider as tjp

Lokal = {"id": 30, "name": "Lokal", "enabled": True, "protocol": "openai_compat", "capabilities": ["tts"],
       "base_url": "http://lokal:8000/v1",
       "voices": [{"voice_id": "anna", "name": "Anna", "language": "de"},
                  {"voice_id": "ben", "name": "Ben", "language": "de"},
                  {"voice_id": "nova", "name": "Nova", "language": "en"}]}
MYLAB = {"id": 21, "name": "THL myLab", "enabled": True, "protocol": "openai_compat", "capabilities": ["tts"],
         "base_url": "https://mylab/v1",
         "voices": [{"voice_id": "nova", "name": "Nova", "language": "en"},
                    {"voice_id": "onyx", "name": "Onyx", "language": "de"},
                    {"voice_id": "echo", "name": "Echo", "language": "de"}]}


@pytest.fixture
def welt(monkeypatch):
    stand = {"anbieter": {30: dict(Lokal), 21: dict(MYLAB)},
             "route": {"provider_id": 30, "fallback_provider_id": 21,
                       "provider_models": {"30": "qwen3-tts", "21": "xtts-v2"}},
             "gesperrt": set(), "unerreichbar": set()}
    monkeypatch.setattr(tjp.db, "get_route", lambda f: stand["route"] if f == "tts" else None)
    monkeypatch.setattr(tjp.db, "get_provider", lambda pid: stand["anbieter"].get(pid))
    monkeypatch.setattr(tjp, "_marked_down", lambda pid: pid in stand["gesperrt"])
    monkeypatch.setattr(tjp, "_reachable", lambda p: p["id"] not in stand["unerreichbar"])
    return stand


def test_ist_der_gewaehlte_da_bleibt_alles_wie_gewaehlt(welt):
    wahl = tjp.pick(30, ["anna"])
    assert (wahl.provider_id, wahl.voices, wahl.fallback) == (30, ("anna",), False)


def test_nicht_erreichbar_laeuft_der_ganze_auftrag_mit_dem_rueckfall(welt):
    welt["unerreichbar"].add(30)
    wahl = tjp.pick(30, ["nova"])
    assert (wahl.provider_id, wahl.voices, wahl.fallback) == (21, ("nova",), True)


def test_ein_sperrvermerk_reicht_fuer_den_rueckfall(welt):
    welt["gesperrt"].add(30)
    assert tjp.pick(30, ["nova"]).provider_id == 21


def test_ein_ausgeschalteter_anbieter_zaehlt_als_nicht_da(welt):
    welt["anbieter"][30]["enabled"] = False
    assert tjp.pick(30, ["nova"]).provider_id == 21


def test_fehlt_die_stimme_nimmt_er_eine_in_derselben_sprache(welt):
    welt["unerreichbar"].add(30)
    assert tjp.pick(30, ["anna"]).voices == ("onyx",)


def test_zwei_personen_bekommen_verschiedene_stimmen(welt):
    welt["unerreichbar"].add(30)
    assert tjp.pick(30, ["anna", "ben"]).voices == ("onyx", "echo")


def test_dieselbe_stimme_zweimal_bleibt_dieselbe(welt):
    welt["unerreichbar"].add(30)
    assert tjp.pick(30, ["anna", "anna"]).voices == ("onyx", "onyx")


def test_ohne_passende_sprache_nimmt_er_die_erste_freie_stimme(welt):
    welt["unerreichbar"].add(30)
    welt["anbieter"][21]["voices"] = [{"voice_id": "alloy", "name": "Alloy", "language": "en"}]
    assert tjp.pick(30, ["anna"]).voices == ("alloy",)


@pytest.mark.parametrize("aenderung", [
    lambda w: w["route"].update(fallback_provider_id=None),
    lambda w: w["route"].update(fallback_provider_id=30),
    lambda w: w["route"]["provider_models"].pop("21"),
    lambda w: w["anbieter"][21].update(enabled=False),
    lambda w: w["anbieter"][21].update(protocol="deepl"),
    lambda w: w["anbieter"][21].update(capabilities=["chat"]),
    lambda w: w["anbieter"][21].update(voices=[]),
    lambda w: w["unerreichbar"].add(21),
])
def test_ein_unbrauchbarer_rueckfall_laesst_den_gewaehlten_stehen(welt, aenderung):
    """Then the job fails or waits as today, it does not jump into the void."""
    welt["unerreichbar"].add(30)
    aenderung(welt)
    wahl = tjp.pick(30, ["anna"])
    assert (wahl.provider_id, wahl.voices, wahl.fallback) == (30, ("anna",), False)


def test_wer_den_rueckfall_selbst_waehlt_bekommt_ihn_ohne_umweg(welt):
    welt["unerreichbar"].add(21)
    wahl = tjp.pick(21, ["nova"])
    assert (wahl.provider_id, wahl.fallback) == (21, False)


def test_der_name_der_stimme_kommt_vom_anbieter(welt):
    assert tjp.voice_name(21, "onyx") == "Onyx"
    assert tjp.voice_name(21, "unbekannt") == "unbekannt"


def test_schon_vergebene_stimmen_des_rueckfalls_bleiben_frei(welt):
    """Podcast with two providers: the person already speaking at myLab keeps their voice."""
    welt["unerreichbar"].add(30)
    assert tjp.pick(30, ["anna"], taken=["onyx"]).voices == ("echo",)


def test_stimmen_ohne_kennung_werden_nie_zugeordnet(welt):
    welt["unerreichbar"].add(30)
    welt["anbieter"][21]["voices"] = [{"voice_id": "", "name": "?", "language": "de"},
                                      {"voice_id": "alloy", "name": "Alloy", "language": "en"}]
    assert tjp.pick(30, ["anna"]).voices == ("alloy",)


def test_ein_rueckfall_nur_mit_stimmen_ohne_kennung_zaehlt_nicht(welt):
    welt["unerreichbar"].add(30)
    welt["anbieter"][21]["voices"] = [{"voice_id": "", "name": "?"}]
    assert tjp.pick(30, ["anna"]).provider_id == 30


# ─── Is the file really missing or was only the read disturbed ───────────


def test_nur_eine_fehlende_datei_gilt_als_fehlend():
    from botocore.exceptions import ClientError

    from src import storage

    assert storage.is_missing(FileNotFoundError("weg"))
    assert storage.is_missing(ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject"))
    assert storage.is_missing(ClientError({"Error": {"Code": "404"}}, "GetObject"))
    assert not storage.is_missing(ClientError({"Error": {"Code": "SlowDown"}}, "GetObject"))
    assert not storage.is_missing(TimeoutError("langsam"))
    assert not storage.is_missing(ValueError("kaputtes JSON"))
