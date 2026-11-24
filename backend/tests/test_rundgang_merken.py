"""Whether someone already did the tour belongs on the account, not in one browser."""

import asyncio
from datetime import datetime

import pytest

from src.routes import me as routes

NUTZER = {"user_id": 5}

KONTO = {
    "id": 5, "username": "cc", "display_name": "Carla", "email": "cc@example.org",
    "role": "staff", "locale": "de",
}


@pytest.fixture
def konto_mit(monkeypatch):
    def einrichten(tour_seen_at):
        monkeypatch.setattr(routes.db, "get_user_by_id", lambda uid: {**KONTO, "tour_seen_at": tour_seen_at})
        monkeypatch.setattr(
            routes.db, "get_user_language_level",
            lambda uid: {"language_level": None, "language_level_set_at": None},
        )
    return einrichten


def test_wer_den_rundgang_noch_nie_gesehen_hat(konto_mit):
    konto_mit(None)
    assert (routes.get_me(NUTZER, "de"))["tour_seen_at"] is None


def test_wer_ihn_schon_gesehen_hat_bekommt_den_zeitpunkt(konto_mit):
    konto_mit(datetime(2026, 9, 2, 12, 0))
    antwort = (routes.get_me(NUTZER, "de"))
    assert antwort["tour_seen_at"].startswith("2026-09-02")


def test_erledigt_melden_schreibt_den_zeitpunkt(monkeypatch):
    gemerkt = {}
    monkeypatch.setattr(routes.db, "set_user_tour_seen", lambda uid, seen: gemerkt.update(uid=uid, seen=seen))
    antwort = (routes.update_tour_seen(routes.TourSeenUpdate(seen=True), NUTZER, "de"))
    assert gemerkt == {"uid": 5, "seen": True}
    assert antwort["seen"] is True


def test_man_kann_den_rundgang_wieder_freischalten(monkeypatch):
    """Otherwise nobody could get the invitation back, not even for a demo."""
    gemerkt = {}
    monkeypatch.setattr(routes.db, "set_user_tour_seen", lambda uid, seen: gemerkt.update(uid=uid, seen=seen))
    antwort = (routes.update_tour_seen(routes.TourSeenUpdate(seen=False), NUTZER, "de"))
    assert gemerkt == {"uid": 5, "seen": False}
    assert antwort["seen"] is False


def test_der_werkzeug_rundgang_hat_keinen_merker_mehr(konto_mit):
    """The tools tour is gone, the tile overview explains every tool itself."""
    konto_mit(None)
    assert "tools_tour_seen_at" not in (routes.get_me(NUTZER, "de"))
    assert not hasattr(routes, "update_tools_tour_seen")
