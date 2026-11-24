"""A spoken example sentence is one job: the provider is chosen once per sentence. If the configured voice is down at start, the admin fallback speaks the whole sentence and the audio is stored under the fallback's key, never the first choice's; the voice preview asks exactly the named provider."""
import pytest

from src.features.ai_assistant.repository import speech_cache
from src.services import aia_flashcard_speech as speech
from src.services import tts_job_provider as tjp
from src.services import tts_voice_preview

MYLAB = {"id": 21, "name": "THL myLab", "enabled": True, "protocol": "openai_compat", "capabilities": ["tts"],
         "base_url": "https://mylab/v1",
         "voices": [{"voice_id": "alloy", "name": "Alloy", "language": "de"}]}
Lokal = {"id": 30, "name": "Lokal", "enabled": True, "protocol": "openai_compat", "capabilities": ["tts"],
       "base_url": "http://lokal:8000/v1",
       "voices": [{"voice_id": "anna", "name": "Anna", "language": "de"}]}
_MODELLE = {21: "xtts-v2", 30: "qwen3-tts"}


class _Client:
    """A provider that records who was asked with which voice."""

    def __init__(self, pid):
        self.pid = pid
        self.aufrufe = []

    def synthesize_chunk(self, text, *, voice_id, speed=1.0, **kwargs):
        self.aufrufe.append((self.pid, text, voice_id))
        return f"ton-{self.pid}-{voice_id}".encode()

    def is_available(self):
        return True


@pytest.fixture
def welt(monkeypatch):
    """Settings, providers, pool and clients without a database or network."""
    stand = {"einstellungen": {"aia_flashcard_voice_provider_id": "21", "aia_flashcard_voice_id": "alloy"},
             "anbieter": {21: dict(MYLAB), 30: dict(Lokal)},
             "route": {"provider_id": 21, "fallback_provider_id": 30,
                       "provider_models": {"21": "xtts-v2", "30": "qwen3-tts"}},
             "unerreichbar": set(), "vorrat": {}, "clients": {}, "wahlen": []}
    monkeypatch.setattr("src.database.get_setting",
                        lambda key, default="": stand["einstellungen"].get(key, default))
    monkeypatch.setattr(tjp.db, "get_route", lambda f: stand["route"] if f == "tts" else None)
    monkeypatch.setattr(tjp.db, "get_provider", lambda pid: stand["anbieter"].get(pid))
    monkeypatch.setattr(tjp, "_marked_down", lambda pid: False)
    monkeypatch.setattr(tjp, "_reachable", lambda p: p["id"] not in stand["unerreichbar"])
    echte_wahl = tjp.pick

    def wahl(provider_id, voice_ids):
        stand["wahlen"].append((provider_id, list(voice_ids)))
        return echte_wahl(provider_id, voice_ids)

    monkeypatch.setattr(tjp, "pick", wahl)
    monkeypatch.setattr(speech_cache, "get", lambda key: stand["vorrat"].get(key))
    monkeypatch.setattr(speech_cache, "put", lambda key, audio: stand["vorrat"].__setitem__(key, audio))
    monkeypatch.setattr("src.dependencies.tts_model_for_provider", lambda pid: _MODELLE.get(pid, ""))
    monkeypatch.setattr("src.dependencies.get_tts_client_for_provider",
                        lambda pid, user_id=None: stand["clients"].setdefault(pid, _Client(pid)))
    monkeypatch.setattr("src.dependencies._voice_language_for", lambda pid, vid: "de")
    return stand


def _gefragt(welt):
    return [aufruf for client in welt["clients"].values() for aufruf in client.aufrufe]


def test_ist_die_erste_wahl_da_spricht_sie_den_satz(welt):
    assert speech.synthesize_sentence("Ein Satz.") == b"ton-21-alloy"
    assert _gefragt(welt) == [(21, "Ein Satz.", "alloy")]


def test_die_wahl_faellt_einmal_je_satz_mit_der_eingestellten_stimme(welt):
    speech.synthesize_sentence("Ein Satz.")
    assert welt["wahlen"] == [(21, ["alloy"])]


def test_faellt_die_erste_wahl_aus_spricht_der_rueckfall_den_ganzen_satz(welt):
    welt["unerreichbar"].add(21)
    assert speech.synthesize_sentence("Ein Satz.") == b"ton-30-anna"
    assert _gefragt(welt) == [(30, "Ein Satz.", "anna")]


def test_der_rueckfall_landet_unter_seinem_eigenen_schluessel(welt):
    """Otherwise the fallback voice would later be served as the first choice's sound."""
    welt["unerreichbar"].add(21)
    speech.synthesize_sentence("Ein Satz.")
    eigener = speech_cache.fingerprint("Ein Satz.", 30, "anna", 1.0, "qwen3-tts")
    erste_wahl = speech_cache.fingerprint("Ein Satz.", 21, "alloy", 1.0, "xtts-v2")
    assert list(welt["vorrat"]) == [eigener]
    assert erste_wahl not in welt["vorrat"]


def test_ist_die_erste_wahl_zurueck_wird_wieder_mit_ihr_gesprochen(welt):
    """A new sentence decides anew, the fallback's sound does not stick."""
    welt["unerreichbar"].add(21)
    speech.synthesize_sentence("Ein Satz.")
    welt["unerreichbar"].clear()
    assert speech.synthesize_sentence("Ein Satz.") == b"ton-21-alloy"
    assert _gefragt(welt)[-1] == (21, "Ein Satz.", "alloy")


def test_ohne_brauchbaren_rueckfall_bleibt_es_beim_eingestellten(welt):
    welt["unerreichbar"].update({21, 30})
    assert speech.synthesize_sentence("Ein Satz.") == b"ton-21-alloy"


def test_die_vorschau_fragt_genau_den_genannten_anbieter(welt, monkeypatch):
    """The preview lets the admin hear exactly this voice, a fallback would lie to them."""
    welt["unerreichbar"].add(21)
    monkeypatch.setattr(tjp, "pick", lambda *a, **kw: pytest.fail("die Vorschau darf nicht umlenken"))
    assert tts_voice_preview.preview_audio(21, "alloy") == b"ton-21-alloy"
    assert [(pid, vid) for pid, _text, vid in _gefragt(welt)] == [(21, "alloy")]


def test_ein_schon_gesprochener_satz_kommt_aus_dem_vorrat_auch_wenn_die_erste_wahl_aus_ist(welt):
    """The chosen voice's sound is still right, only a missing sentence needs the fallback."""
    welt["vorrat"][speech_cache.fingerprint("Ein Satz.", 21, "alloy", 1.0, "xtts-v2")] = b"alt-21-alloy"
    welt["unerreichbar"].add(21)
    assert speech.synthesize_sentence("Ein Satz.") == b"alt-21-alloy"
    assert _gefragt(welt) == []


def test_ein_satz_im_vorrat_braucht_keine_wahl(welt):
    welt["vorrat"][speech_cache.fingerprint("Ein Satz.", 21, "alloy", 1.0, "xtts-v2")] = b"alt-21-alloy"
    speech.synthesize_sentence("Ein Satz.")
    assert welt["wahlen"] == []


def test_der_ton_des_rueckfalls_kommt_beim_naechsten_mal_aus_dem_vorrat(welt):
    welt["unerreichbar"].add(21)
    speech.synthesize_sentence("Ein Satz.")
    assert speech.synthesize_sentence("Ein Satz.") == b"ton-30-anna"
    assert _gefragt(welt) == [(30, "Ein Satz.", "anna")]
