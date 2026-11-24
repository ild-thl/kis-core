"""Pure rules of the event stamp card, without database and without Redis."""
import hashlib
import hmac
import re
from datetime import date

# No I, O, 0 or 1, so a code read off a poster cannot be mixed up.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 4
# A visitor's own code, longer than a stand's so the two are never confused.
VISITOR_CODE_LENGTH = 6
MAX_TILES = 4
# Where a tile shows: in the event block, as the banner under the header, both, or nowhere.
TILE_PLACEMENTS = ("block", "banner", "both", "none")
TILE_TARGET_KINDS = ("stamp", "info", "internal", "directLogin")
# The task card's three tasks, the first is ticked by the chat, the other two by opening their demo.
TASK_IDS = ("question", "praesentation", "screencast")
CLIENT_TASK_IDS = ("praesentation", "screencast")

# The browser makes the id up, anything else is a stray request.
_VISITOR_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# One at sign with something on both sides and a dot in the domain, mail servers judge the rest.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_MAX_LENGTH = 254
# The texts of the raffle the admin writes in both languages.
RAFFLE_TEXT_FIELDS = ("title", "text", "consent", "done")
# The texts of the stamp card page itself, its name and what a full card says.
CARD_TEXT_FIELDS = ("title", "intro", "completeTitle", "completeText")

# The fields a visitor may see of a stand, the code is deliberately missing.
_PUBLIC_STATION_FIELDS = ("id", "icon", "name", "blurb", "francis")


class EventValidationError(ValueError):
    """The configuration breaks a rule, the key names the message and the params fill it."""

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


def _text2(value) -> dict:
    """A text pair as stored, anything that is not one becomes two empty strings."""
    wert = value if isinstance(value, dict) else {}
    return {"de": str(wert.get("de") or ""), "en": str(wert.get("en") or "")}


def _text(de: str, en: str) -> dict:
    return {"de": de, "en": en}


def _station(id: str, code: str, icon: str, de: tuple[str, str, str], en: tuple[str, str, str]) -> dict:
    return {
        "id": id,
        "code": code,
        "icon": icon,
        "name": _text(de[0], en[0]),
        "blurb": _text(de[1], en[1]),
        "francis": _text(de[2], en[2]),
    }


def default_config() -> dict:
    """The stands and the event block a fresh install shows until the admin saves its own."""
    return {
        "hideCodeOnPosters": False,
        "stations": [
            _station(
                "management", "H4RV", "info",
                ("Projekt KIS", "Ziele, Antrag und Zeitplan",
                 "Hier hast du gesehen, wofür das Projekt KIS steht und wie es aufgebaut ist."),
                ("Project KIS", "Goals, proposal and schedule",
                 "Here you saw what the KIS project stands for and how it is organised."),
            ),
            _station(
                "study", "P9KT", "francis",
                ("Studium", "Assistent, Microcredentials und Fachlandkarte",
                 "Hier hast du gesehen, wie das Studium auf internationale Studierende abgestimmt wird."),
                ("Studies", "Assistant, microcredentials and subject map",
                 "Here you saw how the degree programme is adapted for international students."),
            ),
            _station(
                "platform", "M3XD", "platform",
                ("askFrancis", "KI-Fachsprachen-Trainer und Übersetzung",
                 "Hier hast du gesehen, wie askFrancis Materialien übersetzt und beim Fachwortschatz hilft."),
                ("askFrancis", "AI technical-language trainer and translation",
                 "Here you saw how askFrancis translates materials and helps with technical vocabulary."),
            ),
            _station(
                "dafl", "W7NC", "translation",
                ("Deutsch als Fremdsprache", "Sprachkurse und Buddy-Programm",
                 "Hier hast du gesehen, wie Deutschkurse und Buddys internationale Studierende begleiten."),
                ("German as a foreign language", "Language courses and buddy programme",
                 "Here you saw how German courses and buddies support international students."),
            ),
            _station(
                "intercultural", "T6QB", "lightbulb",
                ("Interkulturelle Kompetenzen", "Lernfortschritt und Berufseinstieg",
                 "Hier hast du gesehen, wie Lernstand und Berufseinstieg begleitet werden."),
                ("Intercultural skills", "Learning progress and career entry",
                 "Here you saw how learning progress and the move into work are supported."),
            ),
        ],
        "eventBlock": {
            "enabled": True,
            "ignoreWindow": False,
            "from": "2026-11-06",
            "until": "2026-11-13",
            "heading": _text("Tag der Lehre am 13.11.2026", "Tag der Lehre on 13 November 2026"),
            "text": _text(
                "askFrancis wird vorgestellt. Probiere es direkt aus oder sammle Stempel an allen Ständen.",
                "askFrancis is presented. Try it right away or collect stamps at all stands.",
            ),
            "tiles": [
                {
                    "id": "demo",
                    "icon": "francis",
                    "title": _text("Demozugang", "Demo access"),
                    "body": _text(
                        "Teste askFrancis mit einem Demo-Konto.",
                        "Try askFrancis with a demo account.",
                    ),
                    "button": _text("Ausprobieren", "Try it"),
                    "target": {"kind": "directLogin", "accessCode": "ASKF-DEMO-0000"},
                    "active": False,
                    "availableFrom": "2026-11-13",
                    "placement": "block",
                },
                {
                    "id": "stamp",
                    "icon": "star",
                    "title": _text("Catch Francis", "Catch Francis"),
                    "body": _text(
                        "Besuche alle Stände, sammle Stempel und hol dir am Ende dein Geschenk ab.",
                        "Visit all stands, collect stamps and pick up your gift at the end.",
                    ),
                    "button": _text("Karte öffnen", "Open card"),
                    "target": {"kind": "stamp"},
                    "active": False,
                    "availableFrom": "2026-11-13",
                    "placement": "block",
                },
            ],
        },
        "taskCard": default_task_card(),
        "raffle": default_raffle(),
        "cardTexts": default_card_texts(),
    }


def default_card_texts() -> dict:
    """Name and closing words of the stamp card page, a first draft the admin rewrites at will."""
    return {
        "title": _text("Catch Francis", "Catch Francis"),
        "intro": _text(
            "Francis hat sich an allen Ständen versteckt. Finde ihn überall und sammle an jedem Stand einen Stempel.",
            "Francis is hiding at every stand. Find him everywhere and collect a stamp at each one.",
        ),
        "completeTitle": _text("Gefangen! Du hast Francis an jedem Stand gefunden", "Caught! You found Francis at every stand"),
        "completeText": _text("Hol dir dein Geschenk am Info-Stand ab.", "Pick up your gift at the info stand."),
    }


def default_task_card() -> dict:
    """The task card stays off until the admin switches it on and names its code and workspace."""
    return {
        "enabled": False,
        "ignoreWindow": True,
        "from": "2026-11-13",
        "until": "2026-11-13",
        "accessCode": "ASKF-DEMO-0000",
        "workspace": "",
        "forEveryone": True,
    }


# Names every purpose the addresses serve and the right to withdraw, as consent needs before it is given.
CONSENT_DE = (
    "Ich willige ein, dass meine E-Mail-Adresse für die Verlosung genutzt wird und dass ich zur Mitwirkung "
    "an der Weiterentwicklung von askFrancis kontaktiert werde, etwa für Tests oder Befragungen. Die Adresse "
    "wird nach dem Pilotprojekt gelöscht. Ich kann die Einwilligung jederzeit widerrufen."
)
CONSENT_EN = (
    "I agree that my email address is used for the raffle and that I may be contacted to take part in the "
    "further development of askFrancis, for example for tests or surveys. The address is deleted after the "
    "pilot project. I can withdraw my consent at any time."
)


def default_raffle() -> dict:
    """The raffle under a full card stays off until the admin switches it on, its texts are a first draft."""
    return {
        "enabled": False,
        "title": _text("Verlosung", "Raffle"),
        "text": _text(
            "Unter allen, die Francis an jedem Stand gefunden haben, verlosen wir drei XXL-Tafeln Ritter Sport.",
            "Among everyone who found Francis at every stand we are giving away three XXL bars of Ritter Sport.",
        ),
        "consent": _text(CONSENT_DE, CONSENT_EN),
        "done": _text(
            "Teilnahme bestätigt. Gewinner werden per E-Mail benachrichtigt.",
            "Entry confirmed. Winners are notified by email.",
        ),
    }


def public_raffle(raffle: dict) -> dict | None:
    """The raffle texts a visitor sees, None while the admin keeps it off."""
    if not raffle.get("enabled"):
        return None
    return {feld: raffle[feld] for feld in RAFFLE_TEXT_FIELDS}


def normalize_email(text: str) -> str:
    return text.strip().lower()


def is_valid_email(email: str) -> bool:
    return 0 < len(email) <= EMAIL_MAX_LENGTH and _EMAIL.match(email) is not None


# --- visitors -----------------------------------------------------------------

def is_valid_visitor_id(value: str | None) -> bool:
    return bool(value) and _VISITOR_ID.match(value) is not None


def visitor_hash(visitor_id: str) -> str:
    """Only this hash is ever stored, the id itself stays in the browser."""
    return hashlib.sha256(visitor_id.encode("utf-8")).hexdigest()


# --- codes --------------------------------------------------------------------

def normalize_code(text: str) -> str:
    """Spaces, dashes and case do not matter when a code is read off a poster or a screen."""
    return "".join(text.split()).replace("-", "").upper()


def is_valid_code(code: str) -> bool:
    return len(code) == CODE_LENGTH and all(zeichen in CODE_ALPHABET for zeichen in code)


def station_by_code(stations: list[dict], entered: str) -> dict | None:
    """The stand behind a typed code, every stand is compared so timing tells nothing."""
    code = normalize_code(entered)
    treffer = [stand for stand in stations if hmac.compare_digest(normalize_code(stand["code"]), code)]
    return treffer[0] if treffer else None


# --- time window --------------------------------------------------------------

def is_valid_date_or_empty(value: str) -> bool:
    if value == "":
        return True
    if _ISO_DATE.match(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def event_block_visible(block: dict, today: date) -> bool:
    """Whether the block is shown today, an empty bound leaves that side open."""
    if not block.get("enabled"):
        return False
    if block.get("ignoreWindow"):
        return True
    heute = today.isoformat()
    von, bis = block.get("from") or "", block.get("until") or ""
    return (not von or von <= heute) and (not bis or heute <= bis)


def event_window(config: dict, today: date) -> dict | None:
    """The stamp card's own switch and date, None while the event is off, over or has no stamp tile."""
    block = config["eventBlock"]
    if not block.get("enabled"):
        return None
    heute = today.isoformat()
    if not block.get("ignoreWindow") and (block.get("until") or "") and heute > block["until"]:
        return None
    kachel = next(
        (t for t in block.get("tiles", []) if (t.get("target") or {}).get("kind") == "stamp" and placement_of(t) != "none"),
        None,
    )
    if kachel is None:
        return None
    return {
        "active": bool(kachel.get("active")),
        "availableFrom": kachel.get("availableFrom") or "",
        "title": kachel.get("title") or _text("", ""),
        "body": kachel.get("body") or _text("", ""),
    }


def placement_of(tile: dict) -> str:
    """The tile's placement, a tile saved before the field existed counts as hidden or in the block."""
    wert = tile.get("placement")
    if wert in TILE_PLACEMENTS:
        return wert
    return "none" if tile.get("hidden") else "block"


def _without_hidden_tiles(block: dict) -> dict:
    """The block as visitors get it, tiles placed nowhere never leave the server."""
    return {**block, "tiles": [t for t in block.get("tiles", []) if placement_of(t) != "none"]}


def public_view(config: dict, today: date) -> dict:
    """What a visitor may see: the stands without their codes, the block only inside its window."""
    block = config["eventBlock"]
    return {
        "stations": [
            {feld: stand[feld] for feld in _PUBLIC_STATION_FIELDS} for stand in config["stations"]
        ],
        "eventBlock": _without_hidden_tiles(block) if event_block_visible(block, today) else None,
        "stamp": event_window(config, today),
        "raffle": public_raffle(config["raffle"]),
        "cardTexts": config["cardTexts"],
    }


# --- the card -----------------------------------------------------------------

def completed_at(stamped: dict[str, int], station_ids) -> int | None:
    """The last stamp once every current stand is stamped, stamps of removed stands do not count."""
    ids = list(station_ids)
    if not ids or any(stand_id not in stamped for stand_id in ids):
        return None
    return max(stamped[stand_id] for stand_id in ids)


def build_card(*, stamped: dict[str, int], station_ids, locked_until: int | None, attempts_left: int) -> dict:
    """The card as the browser shows it, trimmed to the stands that exist right now."""
    ids = list(station_ids)
    aktuell = {stand_id: stamped[stand_id] for stand_id in ids if stand_id in stamped}
    return {
        "stamped": aktuell,
        "completedAt": completed_at(aktuell, ids),
        "lockedUntil": locked_until,
        "attemptsLeft": attempts_left,
    }


# --- the task card ------------------------------------------------------------

def same_access_code(a: str | None, b: str | None) -> bool:
    """Codes compare without case and outer spaces, an empty code never matches."""
    a, b = (a or "").strip().upper(), (b or "").strip().upper()
    return bool(a) and a == b


def task_card_for(card: dict, today: date, user_code: str | None) -> bool:
    """Whether this account sees the task card today, every account or only those from the card's code."""
    if not event_block_visible(card, today):
        return False
    return bool(card.get("forEveryone")) or same_access_code(user_code, card.get("accessCode"))


def tasks_view(done: dict[str, int], workspace: str, workspace_title: str = "") -> dict:
    """The card as the browser shows it, trimmed to the tasks that exist."""
    aktuell = {task_id: done[task_id] for task_id in TASK_IDS if task_id in done}
    return {
        "visible": True,
        "done": aktuell,
        "completedAt": completed_at(aktuell, TASK_IDS),
        "workspace": workspace,
        "workspaceTitle": workspace_title,
    }


# --- the admin form -----------------------------------------------------------

def _validate_stations(roh: list[dict]) -> list[dict]:
    """The stands with trimmed ids and normalised codes, each id and code only once."""
    stations = []
    ids: set[str] = set()
    codes: set[str] = set()
    for stand in roh:
        stand_id = str(stand.get("id", "")).strip()
        if not stand_id:
            raise EventValidationError("event.config.stationIdEmpty")
        if stand_id in ids:
            raise EventValidationError("event.config.stationIdDuplicate", id=stand_id)
        ids.add(stand_id)
        code = normalize_code(str(stand.get("code", "")))
        if not is_valid_code(code):
            raise EventValidationError(
                "event.config.codeInvalid", id=stand_id, length=CODE_LENGTH, alphabet=CODE_ALPHABET
            )
        if code in codes:
            raise EventValidationError("event.config.codeDuplicate", code=code)
        codes.add(code)
        stations.append({**stand, "id": stand_id, "code": code})
    return stations


def _validate_tiles(tiles: list[dict]) -> list[dict]:
    """The tiles with trimmed ids and a placement, at most one of them as the banner."""
    if len(tiles) > MAX_TILES:
        raise EventValidationError("event.config.tooManyTiles", max=MAX_TILES)
    tile_ids: set[str] = set()
    geprueft = []
    for tile in tiles:
        tile_id = str(tile.get("id", "")).strip()
        if not tile_id:
            raise EventValidationError("event.config.tileIdEmpty")
        if tile_id in tile_ids:
            raise EventValidationError("event.config.tileIdDuplicate", id=tile_id)
        tile_ids.add(tile_id)
        ziel = tile.get("target") or {}
        if ziel.get("kind") not in TILE_TARGET_KINDS:
            raise EventValidationError("event.config.targetKindInvalid", id=tile_id)
        ab = tile.get("availableFrom") or ""
        if not is_valid_date_or_empty(ab):
            raise EventValidationError("event.config.dateInvalid", value=ab)
        eintrag = {**tile, "id": tile_id, "availableFrom": ab, "placement": placement_of(tile)}
        eintrag.pop("hidden", None)
        geprueft.append(eintrag)
    if sum(1 for tile in geprueft if tile["placement"] in ("banner", "both")) > 1:
        raise EventValidationError("event.config.oneBanner")
    return geprueft


def _validate_task_card(roh: dict | None) -> dict:
    """The task card with every field in its type, missing ones from the default."""
    karte = {**default_task_card(), **(roh or {})}
    for feld in ("from", "until"):
        if not is_valid_date_or_empty(karte[feld] or ""):
            raise EventValidationError("event.config.dateInvalid", value=karte[feld])
    return {
        "enabled": bool(karte["enabled"]),
        "ignoreWindow": bool(karte["ignoreWindow"]),
        "from": karte["from"] or "",
        "until": karte["until"] or "",
        "accessCode": str(karte["accessCode"] or "").strip(),
        "workspace": str(karte["workspace"] or "").strip(),
        "forEveryone": bool(karte["forEveryone"]),
    }


def validate_config(config: dict) -> dict:
    """Checks the rules of the admin form and returns the config with trimmed ids and normalised codes."""
    stations = _validate_stations(config.get("stations", []))

    block = dict(config.get("eventBlock") or {})
    for feld in ("from", "until"):
        wert = block.get(feld) or ""
        if not is_valid_date_or_empty(wert):
            raise EventValidationError("event.config.dateInvalid", value=wert)
        block[feld] = wert
    block["tiles"] = _validate_tiles(list(block.get("tiles") or []))

    karte = _validate_task_card(config.get("taskCard"))

    verlosung = {**default_raffle(), **(config.get("raffle") or {})}
    verlosung = {
        "enabled": bool(verlosung["enabled"]),
        **{feld: _text2(verlosung.get(feld)) for feld in RAFFLE_TEXT_FIELDS},
    }

    texte = {**default_card_texts(), **(config.get("cardTexts") or {})}

    return {
        "stations": stations,
        "eventBlock": block,
        "hideCodeOnPosters": bool(config.get("hideCodeOnPosters")),
        "taskCard": karte,
        "raffle": verlosung,
        "cardTexts": {feld: _text2(texte.get(feld)) for feld in CARD_TEXT_FIELDS},
    }
