"""The choices of the image tool: format and size as pixels, quality as steps, style and the reading tasks."""

from __future__ import annotations

import io
import json
import math
from pathlib import Path

from src.features.praesentation.bild import OHNE_SCHRIFT

FORMATE: tuple[str, ...] = ("1:1", "16:9", "4:3", "3:4", "9:16")
GROESSEN: tuple[str, ...] = ("klein", "mittel", "gross")

# Fixed pixels per format and size, all sides multiples of 16, about 0.6, 1 and 2 megapixels.
_PIXEL: dict[str, tuple[str, str, str]] = {
    "1:1": ("768x768", "1024x1024", "1440x1440"),
    "16:9": ("1024x576", "1344x768", "1920x1088"),
    "4:3": ("896x672", "1152x864", "1664x1248"),
    "3:4": ("672x896", "864x1152", "1248x1664"),
    "9:16": ("576x1024", "768x1344", "1088x1920"),
}
_FLAECHE: dict[str, float] = {"klein": 0.59e6, "mittel": 1.05e6, "gross": 2.07e6}

# Steps for a full image model, a provider with a distilled one maps them onto its own few steps.
_SCHRITTE: dict[str, int] = {"entwurf": 12, "standard": 28, "hoch": 50}
# myLab crashes on an edit without these, so editing keeps its own scale.
_SCHRITTE_BEARBEITEN: dict[str, int] = {"entwurf": 15, "standard": 25, "hoch": 40}

# Style sentences in English, image models follow English best.
_STILE: dict[str, str] = {
    "keiner": "",
    "foto": "Photorealistic photograph, natural light, sharp focus, realistic details.",
    "illustration": "Clean editorial illustration, clear shapes, harmonious colors.",
    "skizze": "Hand-drawn pencil sketch, loose confident lines, light shading, plain white paper.",
    "aquarell": "Soft watercolor painting, gentle color washes, visible paper texture.",
    "3d": "3D render, soft studio lighting, smooth materials, subtle shadows.",
    "flach": "Flat vector illustration, simple geometric shapes, solid colors, no gradients.",
    "thl": "",
}
STILE: tuple[str, ...] = tuple(_STILE)

_AUFGABEN: dict[str, str] = {
    "beschreiben": ("Describe the image in detail: what it shows, people, objects, setting, colors and mood. "
                    "If it is a chart or diagram, also name what its axes or parts show, the key values and the main "
                    "takeaway. Use short paragraphs."),
    "text": ("Transcribe all text that is visible in the image exactly, keep its order and line breaks. "
             "If there is no text, say so in one sentence."),
    "frage": "Answer the question about the image precisely and only from what the image shows.",
}
AUFGABEN: tuple[str, ...] = tuple(_AUFGABEN)
# The rules of the general image prompt that hold for every task, without its call for detail and image language.
_GRUNDREGELN = ("You help university lecturers with visual content. Only state what is visible, add nothing and do "
                "not guess what is not visible. Do not use semicolons or any type of dash, only periods, commas and "
                "question marks.")
_SPRACHEN: dict[str, str] = {"de": "German", "en": "English"}


def pixel(format_: str, groesse: str) -> str:
    """The pixels for a format and a size, ValueError for anything else."""
    if format_ not in _PIXEL or groesse not in GROESSEN:
        raise ValueError(f"unknown format {format_!r} or size {groesse!r}")
    return _PIXEL[format_][GROESSEN.index(groesse)]


def _auf16(wert: float) -> int:
    return max(256, int(wert // 16) * 16)


def wie_vorlage(breite: int, hoehe: int, groesse: str) -> str:
    """The aspect ratio of the source image at the area of the chosen size, both sides multiples of 16."""
    if groesse not in GROESSEN or breite <= 0 or hoehe <= 0:
        raise ValueError(f"unknown size {groesse!r} or empty image")
    verhaeltnis = breite / hoehe
    h = math.sqrt(_FLAECHE[groesse] / verhaeltnis)
    b = h * verhaeltnis
    # A panorama would get a side of several thousand pixels, providers refuse those.
    faktor = min(1.0, 2048 / max(b, h))
    return f"{_auf16(b * faktor)}x{_auf16(h * faktor)}"


# klein refuses sources beyond 8:1, askFrancis pads anything beyond 4:1 onto a white ground and cuts the band out again.
_MAX_VERHAELTNIS = 4


def ausgleichen(breite: int, hoehe: int) -> tuple[int, int, dict | None]:
    """The canvas a source goes onto and which central band of the result is the source again, None when it fits."""
    if breite > _MAX_VERHAELTNIS * hoehe:
        neu = math.ceil(breite / _MAX_VERHAELTNIS)
        return breite, neu, {"achse": "hoehe", "anteil": round(hoehe / neu, 4)}
    if hoehe > _MAX_VERHAELTNIS * breite:
        neu = math.ceil(hoehe / _MAX_VERHAELTNIS)
        return neu, hoehe, {"achse": "breite", "anteil": round(breite / neu, 4)}
    return breite, hoehe, None


def auffuellen(inhalt: bytes, breite: int, hoehe: int) -> bytes:
    """The source centred on a white canvas of the given size, as PNG."""
    from PIL import Image

    with Image.open(io.BytesIO(inhalt)) as vorlage:
        leinwand = Image.new("RGB", (breite, hoehe), "white")
        leinwand.paste(vorlage.convert("RGB"), ((breite - vorlage.width) // 2, (hoehe - vorlage.height) // 2))
    puffer = io.BytesIO()
    leinwand.save(puffer, format="PNG")
    return puffer.getvalue()


def zuschneiden(inhalt: bytes, zuschnitt: dict) -> bytes:
    """The central band of an edited padded picture, the part that was the source."""
    from PIL import Image

    with Image.open(io.BytesIO(inhalt)) as bild:
        b, h = bild.size
        if zuschnitt["achse"] == "hoehe":
            band = round(h * zuschnitt["anteil"])
            kasten = (0, (h - band) // 2, b, (h - band) // 2 + band)
        else:
            band = round(b * zuschnitt["anteil"])
            kasten = ((b - band) // 2, 0, (b - band) // 2 + band, h)
        puffer = io.BytesIO()
        bild.crop(kasten).save(puffer, format="PNG")
    return puffer.getvalue()


def kleiner(groesse: str) -> str:
    """The same picture shrunk into full HD, for a provider that refuses larger ones (GWDG: height up to 1080)."""
    b, h = map(int, groesse.split("x"))
    faktor = min(1.0, 1080 / h, 1920 / b)
    if faktor >= 1.0:
        return groesse
    return f"{_auf16(b * faktor)}x{_auf16(h * faktor)}"


def schritte(qualitaet: str, *, bearbeiten: bool = False) -> int:
    """The number of steps for a quality level."""
    tabelle = _SCHRITTE_BEARBEITEN if bearbeiten else _SCHRITTE
    if qualitaet not in tabelle:
        raise ValueError(f"unknown quality {qualitaet!r}")
    return tabelle[qualitaet]


def _thl_stil() -> str:
    """The style of the THL slide template, so pictures fit the presentations."""
    datei = Path(__file__).resolve().parents[1] / "praesentation" / "assets" / "thl.json"
    return json.loads(datei.read_text(encoding="utf-8"))["style_text"].strip()


def stiltexte() -> dict[str, str]:
    """Every style with its sentence, for services that fill their own picture instruction from a choice."""
    return {k: _thl_stil() if k == "thl" else v for k, v in _STILE.items() if k != "keiner"}


def bild_prompt(beschreibung: str, stil: str, *, ohne_schrift: bool) -> str:
    """What goes to the image model: the style first, then the subject, the no-lettering sentence last."""
    if stil not in _STILE:
        raise ValueError(f"unknown style {stil!r}")
    stiltext = _thl_stil() if stil == "thl" else _STILE[stil]
    teile = [f"{stiltext} Subject: {beschreibung.strip()}" if stiltext else beschreibung.strip()]
    if ohne_schrift:
        teile.append(OHNE_SCHRIFT)
    return " ".join(teile)


def analyse_anweisung(aufgabe: str, sprache: str, frage: str) -> str:
    """The instruction for reading an image, in the chosen answer language."""
    if aufgabe not in _AUFGABEN or sprache not in _SPRACHEN:
        raise ValueError(f"unknown task {aufgabe!r} or language {sprache!r}")
    if aufgabe == "frage" and not frage.strip():
        raise ValueError("a question task needs a question")
    teile = [_GRUNDREGELN, _AUFGABEN[aufgabe], f"Respond in {_SPRACHEN[sprache]}."]
    if aufgabe == "frage":
        teile.append(f"Question: {frage.strip()}")
    return "\n\n".join(teile)
