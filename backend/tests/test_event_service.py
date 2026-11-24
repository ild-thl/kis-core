"""The rules of the stamp card without storage: window, codes, card, admin form."""
from datetime import date

import pytest

from src.features.event.service import (
    CODE_ALPHABET,
    MAX_TILES,
    EventValidationError,
    build_card,
    completed_at,
    default_config,
    default_card_texts,
    default_raffle,
    is_valid_email,
    normalize_email,
    event_block_visible,
    is_valid_visitor_id,
    normalize_code,
    public_view,
    station_by_code,
    validate_config,
    visitor_hash,
)


# --- the seed -------------------------------------------------------------------

def test_the_seed_carries_neither_master_code_nor_statistics():
    config = default_config()
    assert set(config) == {"stations", "eventBlock", "hideCodeOnPosters", "taskCard", "raffle", "cardTexts"}
    assert config["hideCodeOnPosters"] is False
    assert "masterCode" not in config
    assert len(config["stations"]) == 5
    assert len(config["eventBlock"]["tiles"]) == 2


def test_the_seed_respects_its_own_window():
    """The mockup ignored the window so the demo was always visible, the real page does not."""
    assert default_config()["eventBlock"]["ignoreWindow"] is False


def test_the_seed_passes_its_own_validation():
    config = default_config()
    assert validate_config(config) == config


# --- visitors -------------------------------------------------------------------

@pytest.mark.parametrize("kennung", ["abcdefghijklmnop", "A" * 64, "a-b_c-d_e-f_g-h_i"])
def test_a_visitor_id_of_sixteen_to_sixty_four_safe_characters_passes(kennung):
    assert is_valid_visitor_id(kennung) is True


@pytest.mark.parametrize("kennung", [None, "", "zu-kurz", "A" * 65, "abcdefghijklmno!", "abc def ghij klmn"])
def test_anything_else_is_not_a_visitor_id(kennung):
    assert is_valid_visitor_id(kennung) is False


def test_the_hash_is_sha256_and_never_the_id_itself():
    kennung = "abcdefghijklmnop"
    hash_wert = visitor_hash(kennung)
    assert len(hash_wert) == 64
    assert kennung not in hash_wert
    assert hash_wert == visitor_hash(kennung)


# --- codes ----------------------------------------------------------------------

def test_spaces_and_case_do_not_matter_in_a_code():
    assert normalize_code(" k7 pm ") == "K7PM"


def test_a_stand_is_found_by_its_code_regardless_of_case_and_spaces():
    stations = default_config()["stations"]
    assert station_by_code(stations, " p9 kt")["id"] == "study"
    assert station_by_code(stations, "ZZZZ") is None


# --- the window -----------------------------------------------------------------

BLOCK = {"enabled": True, "ignoreWindow": False, "from": "2026-11-06", "until": "2026-11-13"}


def test_the_block_shows_inside_the_window_including_both_ends():
    assert event_block_visible(BLOCK, date(2026, 11, 6)) is True
    assert event_block_visible(BLOCK, date(2026, 11, 13)) is True
    assert event_block_visible(BLOCK, date(2026, 11, 9)) is True


def test_the_block_hides_outside_the_window():
    assert event_block_visible(BLOCK, date(2026, 11, 5)) is False
    assert event_block_visible(BLOCK, date(2026, 11, 14)) is False


def test_an_empty_bound_leaves_that_side_open():
    assert event_block_visible({**BLOCK, "from": ""}, date(2020, 1, 1)) is True
    assert event_block_visible({**BLOCK, "until": ""}, date(2030, 1, 1)) is True


def test_ignore_window_shows_the_block_whenever_it_is_enabled():
    assert event_block_visible({**BLOCK, "ignoreWindow": True}, date(2030, 1, 1)) is True


def test_a_disabled_block_never_shows():
    assert event_block_visible({**BLOCK, "enabled": False, "ignoreWindow": True}, date(2026, 11, 9)) is False


def test_the_public_view_has_no_codes_and_hides_the_block_outside_the_window():
    sicht = public_view(default_config(), date(2026, 1, 1))
    assert sicht["eventBlock"] is None
    assert all("code" not in stand for stand in sicht["stations"])
    assert set(sicht["stations"][0]) == {"id", "icon", "name", "blurb", "francis"}


def test_the_public_view_shows_the_block_inside_the_window():
    sicht = public_view(default_config(), date(2026, 11, 13))
    assert sicht["eventBlock"]["heading"]["de"].startswith("Tag der Lehre")


# --- the card -------------------------------------------------------------------

def test_the_card_is_complete_at_the_moment_of_the_last_stamp():
    assert completed_at({"a": 100, "b": 300, "c": 200}, ["a", "b", "c"]) == 300


def test_a_missing_stand_means_the_card_is_not_complete():
    assert completed_at({"a": 100, "b": 300}, ["a", "b", "c"]) is None


def test_stamps_of_removed_stands_do_not_count():
    """Only the current stands decide, the stale stamp neither helps nor sets the time."""
    assert completed_at({"a": 100, "alt": 900}, ["a", "b"]) is None
    assert completed_at({"a": 100, "alt": 900}, ["a"]) == 100


def test_without_stands_nobody_is_complete():
    assert completed_at({}, []) is None


def test_the_card_drops_stamps_of_removed_stands():
    karte = build_card(stamped={"a": 100, "alt": 900}, station_ids=["a", "b"], locked_until=None, attempts_left=5)
    assert karte == {"stamped": {"a": 100}, "completedAt": None, "lockedUntil": None, "attemptsLeft": 5}


# --- the admin form -------------------------------------------------------------

def _config(**overrides):
    config = default_config()
    config.update(overrides)
    return config


def _with_station(**felder):
    config = default_config()
    config["stations"][0].update(felder)
    return config


def _with_tile(**felder):
    config = default_config()
    config["eventBlock"]["tiles"][0].update(felder)
    return config


def _key_of(config) -> str:
    with pytest.raises(EventValidationError) as fehler:
        validate_config(config)
    return fehler.value.key


def test_an_empty_stand_id_is_refused():
    assert _key_of(_with_station(id="  ")) == "event.config.stationIdEmpty"


def test_a_duplicate_stand_id_is_refused():
    assert _key_of(_with_station(id="study")) == "event.config.stationIdDuplicate"


@pytest.mark.parametrize("code", ["K7P", "K7PMX", "K0PM", "KIPM", "k7p!"])
def test_a_code_outside_four_safe_characters_is_refused(code):
    assert _key_of(_with_station(code=code)) == "event.config.codeInvalid"


def test_a_code_in_lower_case_with_spaces_is_normalised_on_save():
    gespeichert = validate_config(_with_station(code=" h4 rv "))
    assert gespeichert["stations"][0]["code"] == "H4RV"


def test_two_stands_with_the_same_code_after_normalisation_are_refused():
    assert _key_of(_with_station(code="p9kt")) == "event.config.codeDuplicate"


def test_more_than_four_tiles_are_refused():
    config = default_config()
    kachel = config["eventBlock"]["tiles"][0]
    config["eventBlock"]["tiles"] = [{**kachel, "id": f"k{i}"} for i in range(MAX_TILES + 1)]
    assert _key_of(config) == "event.config.tooManyTiles"


def test_a_duplicate_tile_id_is_refused():
    assert _key_of(_with_tile(id="stamp")) == "event.config.tileIdDuplicate"


def test_an_empty_tile_id_is_refused():
    assert _key_of(_with_tile(id="")) == "event.config.tileIdEmpty"


def test_an_unknown_target_kind_is_refused():
    assert _key_of(_with_tile(target={"kind": "teleport"})) == "event.config.targetKindInvalid"


@pytest.mark.parametrize("datum", ["13.11.2026", "2026-13-01", "2026-11-31", "heute"])
def test_a_date_that_is_not_iso_is_refused(datum):
    assert _key_of(_with_tile(availableFrom=datum)) == "event.config.dateInvalid"
    config = default_config()
    config["eventBlock"]["from"] = datum
    assert _key_of(config) == "event.config.dateInvalid"


def test_empty_dates_are_fine():
    config = default_config()
    config["eventBlock"].update({"from": "", "until": ""})
    config["eventBlock"]["tiles"][0]["availableFrom"] = ""
    assert validate_config(config)["eventBlock"]["from"] == ""


def test_the_alphabet_has_no_look_alikes():
    assert not set("IO01") & set(CODE_ALPHABET)


def test_validation_keeps_the_hide_setting_and_defaults_it_off():
    config = default_config()
    assert validate_config(config)["hideCodeOnPosters"] is False
    assert validate_config({**config, "hideCodeOnPosters": True})["hideCodeOnPosters"] is True


def test_event_window_follows_the_stamp_tile():
    from src.features.event.service import event_window

    tile = {
        "id": "s",
        "target": {"kind": "stamp"},
        "active": False,
        "availableFrom": "2026-11-06",
        "title": {"de": "Stempelkarte", "en": "Stamp card"},
        "body": {"de": "Besuche alle Stände.", "en": "Visit all stands."},
    }
    config = {"eventBlock": {**BLOCK, "tiles": [tile]}}
    assert event_window(config, date(2026, 11, 5)) == {
        "active": False,
        "availableFrom": "2026-11-06",
        "title": {"de": "Stempelkarte", "en": "Stamp card"},
        "body": {"de": "Besuche alle Stände.", "en": "Visit all stands."},
    }
    assert event_window(config, date(2026, 11, 14)) is None
    assert event_window({"eventBlock": {**BLOCK, "tiles": []}}, date(2026, 11, 9)) is None
    assert event_window({"eventBlock": {**BLOCK, "enabled": False, "tiles": [tile]}}, date(2026, 11, 9)) is None


# --- the raffle -----------------------------------------------------------------

def test_the_seed_keeps_the_raffle_off_with_texts_in_both_languages():
    raffle = default_config()["raffle"]
    assert raffle["enabled"] is False
    for feld in ("title", "text", "consent", "done"):
        assert raffle[feld]["de"] and raffle[feld]["en"]


def test_the_public_view_hides_the_raffle_while_it_is_off():
    assert public_view(default_config(), date(2026, 11, 13))["raffle"] is None


def test_the_public_view_shows_the_raffle_texts_without_the_switch():
    config = default_config()
    config["raffle"]["enabled"] = True
    raffle = public_view(config, date(2026, 11, 13))["raffle"]
    assert set(raffle) == {"title", "text", "consent", "done"}
    assert raffle["title"]["de"] == "Verlosung"


def test_the_admin_form_keeps_the_raffle_and_fills_missing_texts():
    config = default_config()
    config["raffle"] = {"enabled": True, "title": {"de": "Gewinnspiel"}}
    raffle = validate_config(config)["raffle"]
    assert raffle["enabled"] is True
    assert raffle["title"] == {"de": "Gewinnspiel", "en": ""}
    assert raffle["consent"] == default_raffle()["consent"]


def test_an_older_form_without_a_raffle_gets_the_seed():
    config = default_config()
    del config["raffle"]
    assert validate_config(config)["raffle"] == default_raffle()


@pytest.mark.parametrize("email", ["a@b.de", "First.Last+tag@sub.example.org"])
def test_plain_addresses_are_valid(email):
    assert is_valid_email(normalize_email(email))


@pytest.mark.parametrize("email", ["", "ohne-at.de", "zwei@@x.de", "a@b", "a b@c.de", "x@" + "y" * 260 + ".de"])
def test_broken_addresses_are_rejected(email):
    assert not is_valid_email(normalize_email(email))


def test_normalising_lowers_and_trims():
    assert normalize_email("  Max@Example.ORG ") == "max@example.org"


# --- texts of the card ------------------------------------------------------------

def test_the_seed_calls_the_card_catch_francis_in_both_languages():
    texte = default_config()["cardTexts"]
    assert texte["title"] == {"de": "Catch Francis", "en": "Catch Francis"}
    for feld in ("intro", "completeTitle", "completeText"):
        assert texte[feld]["de"] and texte[feld]["en"]


def test_the_public_view_carries_the_card_texts():
    assert public_view(default_config(), date(2026, 11, 13))["cardTexts"]["title"]["de"] == "Catch Francis"


def test_the_admin_form_keeps_edited_card_texts_and_fills_the_rest():
    config = default_config()
    config["cardTexts"] = {"title": {"de": "Francis-Jagd", "en": "Francis hunt"}}
    texte = validate_config(config)["cardTexts"]
    assert texte["title"] == {"de": "Francis-Jagd", "en": "Francis hunt"}
    assert texte["completeText"] == default_card_texts()["completeText"]
