"""Loads the place list of the campus map and keeps one indexed page per place."""
import json
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx

from src.features.campus.repository import pages as page_repo
from src.features.campus.repository import places as place_repo
from src.features.campus.services import fetch as fetch_mod
from src.features.campus.services.indexer import EmbedFn, index_markdown
from src.features.campus.services.place_match import show_param


def _lines(label: str, value: dict | None) -> list[str]:
    out = []
    for lang in ("de", "en"):
        v = (value or {}).get(lang)
        if v:
            out.append(f"{label} ({lang}): {v}" if label else v)
    return out


def place_markdown(place: dict) -> str:
    """Everything the map knows about a place, in both languages, as one small page."""
    title = place.get("title") or {}
    name = place.get("name") or {}
    head = " / ".join(dict.fromkeys(v for v in [title.get("de"), title.get("en")] if v)) or place["id"]
    parts = [f"# {head}"]
    if place.get("code"):
        parts.append(f"Gebäude {place['code']} / Building {place['code']}")
    if name:
        parts.append(" / ".join(dict.fromkeys(v for v in [name.get("de"), name.get("en")] if v)))
    desc = place.get("description") or {}
    for lang in ("de", "en"):
        if desc.get(lang):
            parts.append(desc[lang])
    hours = place.get("opening_hours") or {}
    for lang in ("de", "en"):
        block = hours.get(lang) if isinstance(hours, dict) else None
        if block and block.get("slots"):
            parts.append(f"## {block.get('label') or 'Öffnungszeiten'}")
            parts.extend(f"- {s.get('label', '')} {s.get('time', '')}".strip() for s in block["slots"])
    facs = place.get("facilities") or []
    if facs:
        parts.append("## Einrichtungen / Facilities")
        parts.extend(f"- {f.get('de', '')} / {f.get('en', '')}".strip(" /") for f in facs if isinstance(f, dict))
    terms = place.get("terms") or {}
    words = [w for lang in ("de", "en") for w in (terms.get(lang) or [])]
    if words:
        parts.append("Stichwörter / Keywords: " + ", ".join(words))
    return "\n\n".join(parts)


def _page_url(map_url: str) -> str:
    """The map address without query, a folder address always ending in a slash."""
    parts = urlsplit(map_url.strip())
    path = parts.path or "/"
    if not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path += "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def place_url(map_url: str, place: dict) -> str:
    if not map_url.strip():
        return f"place:{place['id']}"
    return f"{_page_url(map_url)}?show={quote(show_param(place))}"


def places_url(map_url: str) -> str:
    """The place list sits next to the map page, so the map brings its own places."""
    return urljoin(_page_url(map_url), "places.json")


def fetch_places(client: httpx.Client, map_url: str) -> bytes:
    """No map means no places, a map without places.json is fine, any other failure raises."""
    if not map_url.strip():
        return b"[]"
    result = fetch_mod.fetch_conditional(client, places_url(map_url))
    if result.status == "gone":
        return b"[]"
    if result.status != "ok":
        raise ValueError(f"places.json not loaded: {result.error or result.status}")
    return result.body


def parse_places(raw: bytes | str) -> list[dict]:
    data = json.loads(raw)
    places = data.get("places") if isinstance(data, dict) else data
    if not isinstance(places, list):
        raise ValueError("places.json carries no list")
    return [p for p in places if isinstance(p, dict) and p.get("id")]


def sync(raw_json: bytes | str, map_url: str, embed: EmbedFn) -> int:
    """Replaces the place table and re-indexes the place pages, returns how many places there are."""
    places = parse_places(raw_json)
    place_repo.replace_places(places)
    known = page_repo.list_page_urls(page_repo.KIND_PLACE)
    seen: set[str] = set()
    for place in places:
        url = place_url(map_url, place)
        seen.add(url)
        title = (place.get("title") or {}).get("de") or place["id"]
        page_id = page_repo.upsert_page(page_repo.KIND_PLACE, url, title=title)
        index_markdown(page_id, title, place_markdown(place), embed)
    for url, page_id in known.items():
        if url not in seen:
            page_repo.delete_page(page_id)
    return len(places)
