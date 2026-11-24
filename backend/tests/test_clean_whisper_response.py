"""The Whisper answer becomes plain text, whatever shape the provider sends."""
from src.services.openai_compat_llm.base import clean_whisper_response


def test_plain_text_stays():
    assert clean_whisper_response("  Hallo Welt \n") == "Hallo Welt"


def test_quoted_text_is_unwrapped():
    assert clean_whisper_response('"Zeile eins\\nZeile zwei"') == "Zeile eins\nZeile zwei"


def test_json_object_gives_its_text():
    raw = '{"text":" Hallo, dies ist ein Test.","usage":{"type":"duration","seconds":7}}'
    assert clean_whisper_response(raw) == "Hallo, dies ist ein Test."


def test_braces_without_text_field_stay():
    assert clean_whisper_response("{kein JSON}") == "{kein JSON}"
