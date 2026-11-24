"""The place list becomes one page each with a link to the map."""
import json

import pytest

from src.features.campus.services import places_sync
from src.features.campus.services.fetch import FetchResult

ORT = {
    "id": "Mensa_B_59", "code": "B.59", "kind": "building",
    "title": {"de": "Mensa B.59", "en": "Mensa (Dining Hall) B.59"}, "name": {"de": "Mensa", "en": "Mensa (dining hall)"},
    "description": {"de": "Drei bis vier Gerichte täglich.", "en": "Three to four dishes a day."},
    "opening_hours": {"de": {"label": "Öffnungszeiten", "slots": [{"label": "Mo - Fr:", "time": "11:15 - 14:15 Uhr"}]}, "en": None},
    "facilities": [{"de": "Mensa", "en": "Mensa (dining hall)"}], "terms": {"de": ["Essen"], "en": ["food"]},
}


def test_markdown_und_url():
    md = places_sync.place_markdown(ORT)
    assert md.startswith("# Mensa B.59 / Mensa (Dining Hall) B.59")
    assert "11:15 - 14:15 Uhr" in md and "Three to four dishes" in md and "Essen, food" in md
    assert places_sync.place_url("https://map.test/campus-map", ORT) == "https://map.test/campus-map/?show=B.59"
    assert places_sync.place_url("", ORT) == "place:Mensa_B_59"


def test_sync_ersetzt_orte_und_seiten(monkeypatch):
    ersetzt = []
    monkeypatch.setattr(places_sync.place_repo, "replace_places", lambda places: ersetzt.append(places) or len(places))
    angelegt = []
    geloescht = []
    monkeypatch.setattr(places_sync.page_repo, "list_page_urls", lambda kind: {"https://map.test/?show=ALT": 7})
    monkeypatch.setattr(places_sync.page_repo, "upsert_page", lambda kind, url, title=None, **kw: angelegt.append((kind, url, title)) or 1)
    monkeypatch.setattr(places_sync.page_repo, "delete_page", lambda pid: geloescht.append(pid))
    indexiert = []
    monkeypatch.setattr(places_sync, "index_markdown", lambda pid, title, md, embed: indexiert.append(title) or 1)
    n = places_sync.sync(json.dumps({"places": [ORT]}), "https://map.test/", lambda t: [])
    assert n == 1 and ersetzt[0][0]["id"] == "Mensa_B_59"
    assert angelegt == [("place", "https://map.test/?show=B.59", "Mensa B.59")]
    assert indexiert == ["Mensa B.59"] and geloescht == [7]


def test_url_mit_index_html():
    url = "https://s3.test/bucket/campus-map/index.html"
    assert places_sync.place_url(url, ORT) == "https://s3.test/bucket/campus-map/index.html?show=B.59"
    assert places_sync.places_url(url) == "https://s3.test/bucket/campus-map/places.json"
    assert places_sync.places_url("https://map.test/campus-map") == "https://map.test/campus-map/places.json"


def test_fetch_places(monkeypatch):
    assert places_sync.fetch_places(None, "") == b"[]"
    monkeypatch.setattr(places_sync.fetch_mod, "fetch_conditional", lambda c, u: FetchResult("gone"))
    assert places_sync.fetch_places(None, "https://map.test/") == b"[]"
    monkeypatch.setattr(places_sync.fetch_mod, "fetch_conditional", lambda c, u: FetchResult("ok", body=b'{"places": []}'))
    assert places_sync.fetch_places(None, "https://map.test/") == b'{"places": []}'
    monkeypatch.setattr(places_sync.fetch_mod, "fetch_conditional", lambda c, u: FetchResult("error", error="http 500"))
    with pytest.raises(ValueError):
        places_sync.fetch_places(None, "https://map.test/")
