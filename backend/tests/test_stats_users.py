"""The user numbers, checked where a number goes quietly wrong."""
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from src.features.stats import users as u


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, args=None):
        pass

    def fetchall(self):
        return self._rows


def test_ein_schluessel_ohne_nutzer_blaeht_die_zahl_nicht_auf():
    """Whoever can be resolved is counted."""
    cur = FakeCursor([{"id": 1, "display_name": "Hans", "username": "h"}])
    ergebnis = u._online_details(cur, {1: 1750000000, 4242: 1750000000})
    assert ergebnis["count"] == 1
    assert [x["name"] for x in ergebnis["users"]] == ["Hans"]


def test_niemand_online_gibt_null_und_leere_liste():
    assert u._online_details(FakeCursor([]), {}) == {"count": 0, "users": []}


def test_ohne_namen_steht_der_anmeldename():
    cur = FakeCursor([{"id": 2, "display_name": "", "username": "mmuster"}])
    assert u._online_details(cur, {2: 1750000000})["users"][0]["name"] == "mmuster"


def test_ohne_beides_steht_unbekannt():
    cur = FakeCursor([{"id": 3, "display_name": None, "username": None}])
    assert u._online_details(cur, {3: 1750000000})["users"][0]["name"] == "Unbekannt"


def test_die_schwelle_fuer_regelmaessig_steht_im_code():
    """An invented number in the chart would be worse than a named one."""
    assert u.REGELMAESSIG_AB_TAGEN == 10


def test_die_drei_gruppen_teilen_die_nutzer_ohne_ueberschneidung():
    cur = MagicMock()
    cur.fetchall.return_value = [
        {"tage": 1, "n": 5},    # exactly once
        {"tage": 4, "n": 3},    # occasional
        {"tage": 10, "n": 2},   # still occasional, threshold is "more than"
        {"tage": 11, "n": 1},   # regular
    ]
    r = u._retention(cur)
    assert (r["once"], r["occasional"], r["regular"]) == (5, 5, 1)
    assert r["once"] + r["occasional"] + r["regular"] == 11


def test_wie_lange_jemand_schon_da_ist():
    """Measured from the first heartbeat, not from the last ping."""
    import time
    cur = FakeCursor([{"id": 1, "display_name": "Hans", "username": "h"}])
    vor_zehn_minuten = int(time.time()) - 600
    assert u._online_details(cur, {1: vor_zehn_minuten})["users"][0]["minutes"] == 10


def test_tagesverlauf_geht_bis_zur_aktuellen_stunde_auch_ohne_spaete_aktivitaet():
    """Nobody online after 18:00 must not cut the timeline off at 18:00."""
    cur = MagicMock()
    cur.fetchall.return_value = [{"hour": 6, "n": 4}, {"hour": 18, "n": 3}]
    mit_uhrzeit = datetime(2026, 8, 31, 22, 59, tzinfo=ZoneInfo("Europe/Berlin"))
    with patch("src.features.stats.users.datetime") as fake_datetime:
        fake_datetime.now.return_value = mit_uhrzeit
        r = u._today_by_hour(cur)
    assert r[-1] == {"hour": 21, "users": 0}
    assert len(r) == 22


def test_stunden_liste_gibt_die_aufgeloesten_namen_zurueck():
    cur = FakeCursor([{"id": 1, "name": "Hans"}, {"id": 2, "name": "Petra"}])
    assert u._users_by_hour(cur, 14) == [{"id": 1, "name": "Hans"}, {"id": 2, "name": "Petra"}]


def test_stunden_liste_ohne_treffer_ist_leer():
    assert u._users_by_hour(FakeCursor([]), 3) == []


def test_tages_liste_gibt_die_aufgeloesten_namen_zurueck():
    cur = FakeCursor([{"id": 5, "name": "Mo"}])
    assert u._users_by_day(cur, "2026-08-27") == [{"id": 5, "name": "Mo"}]


def test_tages_liste_ohne_treffer_ist_leer():
    assert u._users_by_day(FakeCursor([]), "2026-08-27") == []


def test_monats_liste_gibt_die_aufgeloesten_namen_zurueck():
    cur = FakeCursor([{"id": 7, "name": "Timo"}])
    assert u._users_new_in_month(cur, "08/26") == [{"id": 7, "name": "Timo"}]


def test_monats_liste_ohne_treffer_ist_leer():
    assert u._users_new_in_month(FakeCursor([]), "08/26") == []


class CapturingCursor:
    def __init__(self):
        self.sql = None

    def execute(self, sql, args=None):
        self.sql = sql

    def fetchall(self):
        return []


def test_tages_liste_zaehlt_jeden_nutzer_nur_einmal():
    """Whoever was present several hours on one day appears in user_presence more than once."""
    cur = CapturingCursor()
    u._users_by_day(cur, "2026-08-28")
    assert "DISTINCT" in cur.sql


def test_tages_liste_verliert_geloeschte_nutzer_nicht():
    """user_presence keeps rows of deleted users, the chart number counts them too."""
    cur = CapturingCursor()
    u._users_by_day(cur, "2026-08-28")
    assert "LEFT JOIN" in cur.sql


def test_stunden_liste_verliert_geloeschte_nutzer_nicht():
    cur = CapturingCursor()
    u._users_by_hour(cur, 10)
    assert "LEFT JOIN" in cur.sql
