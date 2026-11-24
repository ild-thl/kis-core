"""The public card without a session, the admin form behind its right."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.features.event import repository as repo
from src.features.event.service import default_config
from src.limits import EVENT_CODE_MAX_ATTEMPTS
from src.permissions_registry import PERM_SET_EVENT

BESUCHER = {"X-Visitor-Id": "abcdefghijklmnop0123"}
ANDERER = {"X-Visitor-Id": "zyxwvutsrqponmlk9876"}


@pytest.fixture
def client():
    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth
    from src.app import app

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 1, "email": "admin@example.org", "role": "admin",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def client_ohne_recht():
    """A logged-in user without the event right, to prove the gate holds."""
    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth
    from src.app import app

    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 3, "email": "student@example.org", "role": "user",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def client_mit_event_recht(monkeypatch):
    """A custom role that holds the event page and nothing else of the settings."""
    from src import database
    from src.dependencies import get_current_user, get_settings
    from src.security.auth import verify_auth
    from src.app import app

    monkeypatch.setattr(
        database, "get_custom_role",
        lambda role_id: {"id": role_id, "name": "Event", "permissions": [PERM_SET_EVENT]},
    )
    get_settings.cache_clear()
    app.dependency_overrides[verify_auth] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 4, "email": "event@example.org", "role": "custom", "custom_role_id": 1,
    }
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def client_ohne_sitzung():
    from src.dependencies import get_settings
    from src.app import app

    get_settings.cache_clear()
    app.dependency_overrides.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


class FakeRedis:
    def __init__(self, store: dict):
        self.store = store

    def get(self, key):
        wert = self.store.get(key)
        return None if wert is None else str(wert).encode()

    def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    def expire(self, key, seconds, nx=False):
        return True

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)

    def close(self):
        pass


@pytest.fixture
def speicher(monkeypatch):
    """Stamps in a dict, the counter in a fake Redis, the seed as configuration."""
    zustand = {
        "config": default_config(), "stamps": {}, "redis": {}, "uhr": [1_700_000_000_000], "codes": {},
        "raffle": {}, "withdraws": [0],
    }

    def add_stamp(visitor_hash, station_id):
        karte = zustand["stamps"].setdefault(visitor_hash, {})
        if station_id not in karte:
            zustand["uhr"][0] += 1000
            karte[station_id] = zustand["uhr"][0]

    def visitor_code(visitor_hash):
        codes = zustand["codes"]
        if visitor_hash not in codes:
            codes[visitor_hash] = f"CODE{len(codes)}"
        return codes[visitor_hash]

    def peek_visitor_code(visitor_hash):
        return zustand["codes"].get(visitor_hash, "")

    def visitor_hash_for_code(code):
        for visitor_hash, c in zustand["codes"].items():
            if c == code:
                return visitor_hash
        return None

    monkeypatch.setattr(repo, "get_config", lambda: zustand["config"])
    monkeypatch.setattr(repo, "stamps_for", lambda h: dict(zustand["stamps"].get(h, {})))
    monkeypatch.setattr(repo, "add_stamp", add_stamp)
    monkeypatch.setattr(repo, "delete_stamps_for", lambda h: zustand["stamps"].pop(h, None))
    monkeypatch.setattr(repo, "delete_all_stamps", lambda: zustand["stamps"].clear())
    monkeypatch.setattr(repo, "visitor_code", visitor_code)
    monkeypatch.setattr(repo, "peek_visitor_code", peek_visitor_code)
    monkeypatch.setattr(repo, "visitor_hash_for_code", visitor_hash_for_code)
    monkeypatch.setattr(repo, "delete_all_visitor_codes", lambda: zustand["codes"].clear())
    monkeypatch.setattr(repo, "_redis", lambda: FakeRedis(zustand["redis"]))

    def save_raffle_entry(visitor_hash, email):
        verlosung = zustand["raffle"]
        for h in [h for h, e in verlosung.items() if e == email]:
            del verlosung[h]
        verlosung[visitor_hash] = email

    def delete_by_email(email):
        treffer = [h for h, e in zustand["raffle"].items() if e == email]
        for h in treffer:
            del zustand["raffle"][h]
        return bool(treffer)

    def delete_entry(entry_id):
        eintraege = list(zustand["raffle"])
        if entry_id < 1 or entry_id > len(eintraege):
            return False
        del zustand["raffle"][eintraege[entry_id - 1]]
        return True

    def withdraw_allowed(visitor_hash):
        zustand["withdraws"][0] += 1
        return zustand["withdraws"][0] <= 10

    monkeypatch.setattr(repo, "raffle_email_for", lambda h: zustand["raffle"].get(h))
    monkeypatch.setattr(repo, "save_raffle_entry", save_raffle_entry)
    monkeypatch.setattr(repo, "delete_raffle_entry_by_email", delete_by_email)
    monkeypatch.setattr(repo, "delete_raffle_entry", delete_entry)
    monkeypatch.setattr(repo, "delete_all_raffle_entries", lambda: zustand["raffle"].clear())
    monkeypatch.setattr(
        repo, "raffle_entries",
        lambda: [{"id": i + 1, "email": e, "enteredAt": 1} for i, e in enumerate(zustand["raffle"].values())],
    )
    monkeypatch.setattr(repo, "withdraw_allowed", withdraw_allowed)
    return zustand


# --- public ---------------------------------------------------------------------

def test_the_public_configuration_carries_no_stand_codes(client, speicher):
    r = client.get("/event/public")
    assert r.status_code == 200
    body = r.json()
    assert len(body["stations"]) == 5
    assert all("code" not in stand for stand in body["stations"])
    assert "H4RV" not in r.text


def test_the_public_configuration_hides_the_block_outside_its_window(client, speicher):
    speicher["config"]["eventBlock"].update({"from": "2099-01-01", "until": "2099-01-02"})
    assert client.get("/event/public").json()["eventBlock"] is None


def test_the_public_configuration_shows_the_block_when_the_window_is_ignored(client, speicher):
    speicher["config"]["eventBlock"]["ignoreWindow"] = True
    assert client.get("/event/public").json()["eventBlock"]["tiles"][0]["id"] == "demo"


def test_the_card_needs_a_visitor_id(client, speicher):
    assert client.get("/event/card").status_code == 400
    assert client.get("/event/card", headers={"X-Visitor-Id": "kurz"}).status_code == 400


def test_a_fresh_card_is_empty_with_every_try_left(client, speicher):
    r = client.get("/event/card", headers=BESUCHER)
    assert r.status_code == 200
    assert r.json() == {
        "stamped": {}, "completedAt": None, "lockedUntil": None,
        "attemptsLeft": EVENT_CODE_MAX_ATTEMPTS, "code": "", "raffleEmail": None,
    }


def test_a_bare_page_view_makes_no_visitor_code_only_a_stamp_does(client, speicher):
    assert client.get("/event/card", headers=BESUCHER).json()["code"] == ""
    assert speicher["codes"] == {}
    client.post("/event/stamp", json={"stationId": "study"}, headers=BESUCHER)
    assert client.get("/event/card", headers=BESUCHER).json()["code"] != ""


def test_the_same_visitor_always_gets_the_same_code(client, speicher):
    client.post("/event/stamp", json={"stationId": "study"}, headers=BESUCHER)
    client.post("/event/stamp", json={"stationId": "study"}, headers=ANDERER)
    erst = client.get("/event/card", headers=BESUCHER).json()["code"]
    zweit = client.get("/event/card", headers=BESUCHER).json()["code"]
    assert erst == zweit
    assert client.get("/event/card", headers=ANDERER).json()["code"] != erst


def test_stamping_by_station_id_is_idempotent(client, speicher):
    erster = client.post("/event/stamp", json={"stationId": "study"}, headers=BESUCHER)
    zweiter = client.post("/event/stamp", json={"stationId": "study"}, headers=BESUCHER)
    assert erster.status_code == 200
    assert erster.json()["stationId"] == "study"
    assert zweiter.json()["card"]["stamped"] == erster.json()["card"]["stamped"]
    assert len(zweiter.json()["card"]["stamped"]) == 1


def test_an_unknown_station_is_not_found(client, speicher):
    r = client.post("/event/stamp", json={"stationId": "gibtsnicht"}, headers=BESUCHER)
    assert r.status_code == 404
    assert speicher["stamps"] == {}


def test_only_the_hash_of_the_visitor_id_reaches_storage(client, speicher):
    client.post("/event/stamp", json={"stationId": "study"}, headers=BESUCHER)
    (schluessel,) = speicher["stamps"]
    assert schluessel != BESUCHER["X-Visitor-Id"]
    assert len(schluessel) == 64


def test_two_visitors_keep_separate_cards(client, speicher):
    client.post("/event/stamp", json={"stationId": "study"}, headers=BESUCHER)
    assert client.get("/event/card", headers=ANDERER).json()["stamped"] == {}


def test_the_right_code_stamps_its_stand(client, speicher):
    r = client.post("/event/code", json={"code": " p9 kt"}, headers=BESUCHER)
    assert r.status_code == 200
    body = r.json()
    assert body["result"] == "stamped"
    assert body["stationId"] == "study"
    assert "study" in body["card"]["stamped"]


def test_a_wrong_code_counts_down_and_the_fifth_locks(client, speicher):
    antworten = [
        client.post("/event/code", json={"code": "ZZZZ"}, headers=BESUCHER).json()
        for _ in range(EVENT_CODE_MAX_ATTEMPTS)
    ]
    assert [a["result"] for a in antworten] == ["wrong"] * EVENT_CODE_MAX_ATTEMPTS
    assert [a["card"]["attemptsLeft"] for a in antworten[:-1]] == [4, 3, 2, 1]
    assert all(a["card"]["lockedUntil"] is None for a in antworten[:-1])
    assert antworten[-1]["card"]["lockedUntil"] is not None
    assert antworten[-1]["stationId"] is None


def test_a_locked_visitor_gets_no_comparison_even_with_the_right_code(client, speicher):
    for _ in range(EVENT_CODE_MAX_ATTEMPTS):
        client.post("/event/code", json={"code": "ZZZZ"}, headers=BESUCHER)
    r = client.post("/event/code", json={"code": "P9KT"}, headers=BESUCHER)
    assert r.json()["result"] == "locked"
    assert r.json()["stationId"] is None
    assert r.json()["card"]["stamped"] == {}


def test_a_lock_of_one_visitor_does_not_touch_another(client, speicher):
    for _ in range(EVENT_CODE_MAX_ATTEMPTS):
        client.post("/event/code", json={"code": "ZZZZ"}, headers=BESUCHER)
    assert client.post("/event/code", json={"code": "P9KT"}, headers=ANDERER).json()["result"] == "stamped"


def test_the_card_is_complete_at_the_last_stamp_of_the_current_stands(client, speicher):
    ids = [stand["id"] for stand in speicher["config"]["stations"]]
    for stand_id in ids[:-1]:
        karte = client.post("/event/stamp", json={"stationId": stand_id}, headers=BESUCHER).json()["card"]
        assert karte["completedAt"] is None
    karte = client.post("/event/stamp", json={"stationId": ids[-1]}, headers=BESUCHER).json()["card"]
    assert karte["completedAt"] == max(karte["stamped"].values())


def test_a_removed_stand_takes_its_stamp_and_the_completion_with_it(client, speicher):
    for stand in speicher["config"]["stations"]:
        client.post("/event/stamp", json={"stationId": stand["id"]}, headers=BESUCHER)
    speicher["config"]["stations"].append({**speicher["config"]["stations"][0], "id": "neu", "code": "AAAA"})
    karte = client.get("/event/card", headers=BESUCHER).json()
    assert karte["completedAt"] is None
    speicher["config"]["stations"] = speicher["config"]["stations"][1:]
    karte = client.get("/event/card", headers=BESUCHER).json()
    assert "management" not in karte["stamped"]


# --- without a session ------------------------------------------------------------

def test_the_public_configuration_needs_no_session(client_ohne_sitzung, speicher):
    r = client_ohne_sitzung.get("/event/public")
    assert r.status_code == 200, "401 heisst, das Praefix fehlt im Torwaechter"


def test_the_card_needs_no_session(client_ohne_sitzung, speicher):
    assert client_ohne_sitzung.get("/event/card", headers=BESUCHER).status_code == 200
    assert client_ohne_sitzung.post("/event/code", json={"code": "P9KT"}, headers=BESUCHER).status_code == 200


def test_the_admin_side_still_needs_a_session(client_ohne_sitzung, speicher):
    assert client_ohne_sitzung.get("/admin/event").status_code == 401
    assert client_ohne_sitzung.delete("/admin/event/stamps").status_code == 401


# --- admin ------------------------------------------------------------------------

def test_the_admin_reads_the_configuration_with_codes(client, speicher):
    r = client.get("/admin/event")
    assert r.status_code == 200
    assert r.json()["stations"][0]["code"] == "H4RV"


def test_a_user_without_the_right_is_blocked(client_ohne_recht, speicher):
    assert client_ohne_recht.get("/admin/event").status_code == 403
    assert client_ohne_recht.get("/admin/event/stats").status_code == 403
    assert client_ohne_recht.delete("/admin/event/card", headers=BESUCHER).status_code == 403
    assert client_ohne_recht.delete("/admin/event/stamps").status_code == 403
    with patch.object(repo, "save_config") as speichern:
        assert client_ohne_recht.put("/admin/event", json=default_config()).status_code == 403
    speichern.assert_not_called()


def test_saving_a_valid_configuration_normalises_and_returns_it(client, speicher):
    config = default_config()
    config["stations"][0]["code"] = " h4 rv "
    with patch.object(repo, "save_config") as speichern:
        r = client.put("/admin/event", json=config)
    assert r.status_code == 200
    assert r.json()["stations"][0]["code"] == "H4RV"
    assert speichern.call_args[0][0]["stations"][0]["code"] == "H4RV"
    assert speichern.call_args[0][0]["eventBlock"]["from"] == "2026-11-06"


def test_an_invalid_configuration_is_refused_with_a_localised_message(client, speicher):
    config = default_config()
    config["stations"][1]["code"] = "H4RV"
    with patch.object(repo, "save_config") as speichern:
        de = client.put("/admin/event", json=config, headers={"Accept-Language": "de"})
        en = client.put("/admin/event", json=config, headers={"Accept-Language": "en"})
    assert de.status_code == 422
    assert "H4RV" in de.json()["detail"]
    assert de.json()["detail"] != en.json()["detail"]
    speichern.assert_not_called()


def test_a_fifth_tile_is_refused(client, speicher):
    config = default_config()
    kachel = config["eventBlock"]["tiles"][0]
    config["eventBlock"]["tiles"] = [{**kachel, "id": f"k{i}"} for i in range(5)]
    assert client.put("/admin/event", json=config).status_code == 422


def test_the_statistics_count_visits_per_current_stand_and_complete_cards(client, speicher):
    with patch.object(repo, "visits_by_station", return_value={"study": 3, "alt": 7}), \
         patch.object(repo, "complete_cards", return_value=2) as voll:
        r = client.get("/admin/event/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["visitsByStation"] == {"management": 0, "study": 3, "platform": 0, "dafl": 0, "intercultural": 0}
    assert body["completeCards"] == 2
    voll.assert_called_once_with(["management", "study", "platform", "dafl", "intercultural"])


# --- reset ----------------------------------------------------------------------

def test_the_admin_resets_the_card_of_the_own_browser_only(client, speicher):
    client.post("/event/stamp", json={"stationId": "study"}, headers=BESUCHER)
    client.post("/event/stamp", json={"stationId": "study"}, headers=ANDERER)
    r = client.delete("/admin/event/card", headers=BESUCHER)
    assert r.status_code == 200
    assert r.json()["stamped"] == {}
    assert client.get("/event/card", headers=BESUCHER).json()["stamped"] == {}
    assert "study" in client.get("/event/card", headers=ANDERER).json()["stamped"]


def test_resetting_the_own_card_also_forgets_wrong_tries(client, speicher):
    client.post("/event/code", json={"code": "XXXX"}, headers=BESUCHER)
    assert client.get("/event/card", headers=BESUCHER).json()["attemptsLeft"] == EVENT_CODE_MAX_ATTEMPTS - 1
    client.delete("/admin/event/card", headers=BESUCHER)
    assert client.get("/event/card", headers=BESUCHER).json()["attemptsLeft"] == EVENT_CODE_MAX_ATTEMPTS


def test_resetting_the_own_card_needs_a_visitor_id(client, speicher):
    assert client.delete("/admin/event/card").status_code == 400


def test_the_admin_empties_every_card(client, speicher):
    client.post("/event/stamp", json={"stationId": "study"}, headers=BESUCHER)
    client.post("/event/stamp", json={"stationId": "dafl"}, headers=ANDERER)
    r = client.delete("/admin/event/stamps")
    assert r.status_code == 200
    assert speicher["stamps"] == {}


def test_resetting_every_card_also_drops_every_visitor_code(client, speicher):
    client.post("/event/stamp", json={"stationId": "study"}, headers=BESUCHER)
    assert speicher["codes"]
    client.delete("/admin/event/stamps")
    assert speicher["codes"] == {}


def test_the_event_right_alone_resets_the_own_card_but_not_every_card(client_mit_event_recht, speicher):
    assert client_mit_event_recht.delete("/admin/event/card", headers=BESUCHER).status_code == 200
    assert client_mit_event_recht.delete("/admin/event/stamps").status_code == 403


def test_the_admin_resets_one_visitors_card_by_its_code(client, speicher):
    client.post("/event/stamp", json={"stationId": "study"}, headers=BESUCHER)
    client.post("/event/stamp", json={"stationId": "study"}, headers=ANDERER)
    code = client.get("/event/card", headers=ANDERER).json()["code"]
    r = client.delete(f"/admin/event/card/{code}")
    assert r.status_code == 200
    assert "study" not in client.get("/event/card", headers=ANDERER).json()["stamped"]
    assert "study" in client.get("/event/card", headers=BESUCHER).json()["stamped"]


def test_resetting_by_code_also_forgets_wrong_tries(client, speicher):
    client.post("/event/code", json={"code": "P9KT"}, headers=BESUCHER)
    code = client.get("/event/card", headers=BESUCHER).json()["code"]
    client.post("/event/code", json={"code": "XXXX"}, headers=BESUCHER)
    assert client.get("/event/card", headers=BESUCHER).json()["attemptsLeft"] == EVENT_CODE_MAX_ATTEMPTS - 1
    assert client.delete(f"/admin/event/card/{code}").status_code == 200
    assert client.get("/event/card", headers=BESUCHER).json()["attemptsLeft"] == EVENT_CODE_MAX_ATTEMPTS


def test_an_unknown_visitor_code_is_not_found(client, speicher):
    assert client.delete("/admin/event/card/ZZZZZZ").status_code == 404


def test_the_event_right_alone_can_reset_one_visitors_card(client_mit_event_recht, speicher):
    client_mit_event_recht.post("/event/stamp", json={"stationId": "study"}, headers=BESUCHER)
    code = client_mit_event_recht.get("/event/card", headers=BESUCHER).json()["code"]
    assert client_mit_event_recht.delete(f"/admin/event/card/{code}").status_code == 200


def test_a_user_without_the_right_cannot_reset_one_visitors_card(client_ohne_recht, speicher):
    assert client_ohne_recht.delete("/admin/event/card/ABCDEF").status_code == 403


# --- raffle ---------------------------------------------------------------------

def _voll(client, speicher, kopf=BESUCHER):
    for stand in speicher["config"]["stations"]:
        client.post("/event/stamp", json={"stationId": stand["id"]}, headers=kopf)
    speicher["config"]["raffle"]["enabled"] = True


def test_the_public_view_carries_the_raffle_only_while_it_is_on(client, speicher):
    assert client.get("/event/public").json()["raffle"] is None
    speicher["config"]["raffle"]["enabled"] = True
    assert client.get("/event/public").json()["raffle"]["title"]["de"] == "Verlosung"


def test_a_card_without_entry_shows_no_raffle_address(client, speicher):
    assert client.get("/event/card", headers=BESUCHER).json()["raffleEmail"] is None


def test_the_raffle_is_closed_while_the_admin_keeps_it_off(client, speicher):
    r = client.put("/event/raffle", json={"email": "max@example.org"}, headers=BESUCHER)
    assert r.status_code == 404


def test_an_incomplete_card_cannot_enter_the_raffle(client, speicher):
    speicher["config"]["raffle"]["enabled"] = True
    client.post("/event/stamp", json={"stationId": "study"}, headers=BESUCHER)
    r = client.put("/event/raffle", json={"email": "max@example.org"}, headers=BESUCHER)
    assert r.status_code == 409
    assert speicher["raffle"] == {}


def test_a_full_card_enters_the_raffle_and_the_card_shows_the_address(client, speicher):
    _voll(client, speicher)
    r = client.put("/event/raffle", json={"email": " Max@Example.org "}, headers=BESUCHER)
    assert r.status_code == 200
    assert r.json()["raffleEmail"] == "max@example.org"
    assert client.get("/event/card", headers=BESUCHER).json()["raffleEmail"] == "max@example.org"
    assert list(speicher["raffle"].values()) == ["max@example.org"]


def test_a_broken_address_is_refused_with_a_message(client, speicher):
    _voll(client, speicher)
    r = client.put("/event/raffle", json={"email": "ohne-at"}, headers=BESUCHER)
    assert r.status_code == 422
    assert "E-Mail" in r.json()["detail"]


def test_withdrawing_removes_the_address_and_answers_the_same_either_way(client, speicher):
    _voll(client, speicher)
    client.put("/event/raffle", json={"email": "max@example.org"}, headers=BESUCHER)
    erster = client.post("/event/raffle/withdraw", json={"email": "MAX@example.org"}, headers=ANDERER)
    zweiter = client.post("/event/raffle/withdraw", json={"email": "max@example.org"}, headers=ANDERER)
    assert erster.status_code == zweiter.status_code == 200
    assert erster.json() == zweiter.json() == {"ok": True}
    assert speicher["raffle"] == {}
    assert client.get("/event/card", headers=BESUCHER).json()["raffleEmail"] is None


def test_too_many_withdraw_requests_are_turned_away(client, speicher):
    speicher["withdraws"][0] = 10
    r = client.post("/event/raffle/withdraw", json={"email": "max@example.org"}, headers=ANDERER)
    assert r.status_code == 429


def test_the_admin_lists_and_deletes_raffle_entries(client, speicher):
    _voll(client, speicher)
    client.put("/event/raffle", json={"email": "max@example.org"}, headers=BESUCHER)
    r = client.get("/admin/event/raffle")
    assert r.status_code == 200
    assert r.json()["entries"][0]["email"] == "max@example.org"
    assert client.delete("/admin/event/raffle/1").status_code == 200
    assert client.delete("/admin/event/raffle/1").status_code == 404
    assert client.get("/admin/event/raffle").json()["entries"] == []


def test_the_event_right_alone_reads_the_list_but_cannot_empty_it(client_mit_event_recht, speicher):
    assert client_mit_event_recht.get("/admin/event/raffle").status_code == 200
    assert client_mit_event_recht.delete("/admin/event/raffle").status_code == 403


def test_the_full_admin_empties_the_raffle(client, speicher):
    _voll(client, speicher)
    client.put("/event/raffle", json={"email": "max@example.org"}, headers=BESUCHER)
    assert client.delete("/admin/event/raffle").status_code == 200
    assert speicher["raffle"] == {}


def test_a_user_without_the_right_sees_no_raffle_list(client_ohne_recht, speicher):
    assert client_ohne_recht.get("/admin/event/raffle").status_code == 403


def test_the_admin_form_saves_the_raffle_and_keeps_it_when_the_form_lacks_it(client, speicher, monkeypatch):
    # Saving lands in the fixture, never in the real settings table.
    monkeypatch.setattr(repo, "save_config", lambda config: speicher.__setitem__("config", config))
    config = client.get("/admin/event").json()
    config["raffle"]["enabled"] = True
    config["raffle"]["title"]["de"] = "Gewinnspiel"
    saved = client.put("/admin/event", json=config).json()
    assert saved["raffle"]["enabled"] is True and saved["raffle"]["title"]["de"] == "Gewinnspiel"
    assert speicher["config"]["raffle"]["title"]["de"] == "Gewinnspiel"
    del config["raffle"]
    assert client.put("/admin/event", json=config).json()["raffle"]["title"]["de"] == "Gewinnspiel"
