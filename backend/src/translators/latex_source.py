"""Reads a LaTeX file in any common encoding, writes the result back in it and adapts the preamble to the target language."""

import re
import unicodedata
from pathlib import Path

from loguru import logger

# The inputenc option names LaTeX uses, mapped to Python codecs.
_INPUTENC_CODECS = {
    "utf8": "utf-8", "utf8x": "utf-8",
    "latin1": "cp1252", "ansinew": "cp1252", "cp1252": "cp1252",
    "latin9": "iso8859_15", "latin2": "iso8859_2", "latin3": "iso8859_3",
    "latin4": "iso8859_4", "latin5": "iso8859_9", "latin10": "iso8859_16",
    "cp1250": "cp1250", "cp1251": "cp1251", "cp1257": "cp1257",
    "cp850": "cp850", "cp852": "cp852", "cp437": "cp437", "cp858": "cp858",
    "applemac": "mac_roman", "macce": "mac_latin2", "koi8-r": "koi8_r", "koi8-u": "koi8_u",
}

# Option lists are capped so an unclosed bracket cannot make each match scan the rest of the file.
_INPUTENC_BYTES_RE = re.compile(rb"\\usepackage[ \t]{0,20}\[([^\]]{0,200})\][ \t]{0,20}\{inputenc\}")
_INPUTENC_RE = re.compile(r"(\\usepackage[ \t]{0,20}\[)([^\]]{0,200})(\][ \t]{0,20}\{inputenc\})")


def decode_tex_with_codec(raw: bytes) -> tuple[str, str]:
    """Decodes UTF-8 first, then the encoding the file declares, then Windows-1252 and Latin-1, and names the codec."""
    if b"\x00" in raw:
        raise ValueError("binary content")
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    codecs: list[str] = []
    m = _INPUTENC_BYTES_RE.search(raw)
    if m:
        options = [o.strip().decode("ascii", "ignore") for o in m.group(1).split(b",")]
        codecs.extend(_INPUTENC_CODECS[o] for o in reversed(options) if o in _INPUTENC_CODECS)
    codecs.extend(["cp1252", "latin-1"])
    for codec in codecs:
        try:
            return raw.decode(codec), codec
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def decode_tex(raw: bytes) -> str:
    """Decodes a LaTeX file in any common encoding."""
    return decode_tex_with_codec(raw)[0]


# Characters missing in an 8-bit encoding are written as LaTeX commands, which every encoding accepts.
_TEX_FALLBACK = {
    "“": "``", "”": "''", "‘": "`", "’": "'", "„": "\\quotedblbase{}", "‚": "\\quotesinglbase{}",
    "«": "\\guillemotleft{}", "»": "\\guillemotright{}", "‹": "\\guilsinglleft{}", "›": "\\guilsinglright{}",
    "–": "--", "—": "---", "…": "\\ldots{}", "€": "\\texteuro{}", "•": "\\textbullet{}",
    "‰": "\\textperthousand{}", "™": "\\texttrademark{}", "−": "\\textminus{}", "†": "\\dag{}", "‡": "\\ddag{}",
    "°": "\\textdegree{}", "×": "\\texttimes{}", "±": "\\textpm{}", "µ": "\\textmu{}", "ß": "\\ss{}",
    "\u00a0": "~",
}
_ACCENT_COMMANDS = {
    "\u0308": '\\"', "\u0301": "\\'", "\u0300": "\\`", "\u0302": "\\^", "\u0303": "\\~", "\u0327": "\\c",
    "\u030b": "\\H", "\u030c": "\\v", "\u0306": "\\u", "\u0304": "\\=", "\u0307": "\\.", "\u0328": "\\k",
    "\u030a": "\\r",
}
_C1_BYTES_RE = re.compile(rb"[\x80-\x9f]")


def _tex_fallback(ch: str) -> str:
    if ch in _TEX_FALLBACK:
        return _TEX_FALLBACK[ch]
    decomposed = unicodedata.normalize("NFD", ch)
    if len(decomposed) == 2 and decomposed[1] in _ACCENT_COMMANDS and decomposed[0].isascii():
        return _ACCENT_COMMANDS[decomposed[1]] + "{" + decomposed[0] + "}"
    logger.warning("LaTeX: character U+{:04X} has no form in the file's encoding, written as ?", ord(ch))
    return "?"


def encode_tex(text: str, codec: str, raw: bytes) -> bytes:
    """Writes the result in the encoding of the upload, so it still fits the files that include it."""
    if codec == "utf-8":
        return text.encode("utf-8")
    # Windows-1252 only when the upload used its extra characters, otherwise plain Latin-1 that every 8-bit setup reads.
    if codec == "cp1252":
        codec = "cp1252" if _C1_BYTES_RE.search(raw) else "latin-1"
    out: list[str] = []
    for ch in text:
        if ch.isascii():
            out.append(ch)
            continue
        try:
            ch.encode(codec)
            out.append(ch)
        except UnicodeEncodeError:
            out.append(_tex_fallback(ch))
    return "".join(out).encode(codec)


# A LaTeX file may be this many times larger in bytes than the text limit, heavy markup included.
TEX_BYTES_PER_CHAR = 10


def tex_plain_text(path: str | Path) -> str:
    """The text a LaTeX file in any encoding sends to the translator, used for the length check."""
    from src.translators.latex import translatable_text
    return translatable_text(decode_tex(Path(path).read_bytes()))


def fix_inputenc(text: str) -> str:
    """Sets inputenc to utf8 because the result is always written as UTF-8."""
    return _INPUTENC_RE.sub(lambda m: m.group(1) + "utf8" + m.group(3), text)


# Babel option name for each target language code.
_BABEL_FOR_TARGET = {
    "EN": "english", "EN-US": "english", "EN-GB": "british", "DE": "ngerman",
    "FR": "french", "ES": "spanish", "IT": "italian", "NL": "dutch",
    "PT": "portuguese", "PT-PT": "portuguese", "PT-BR": "brazilian", "PL": "polish",
    "RU": "russian", "UK": "ukrainian", "TR": "turkish", "SV": "swedish",
    "DA": "danish", "FI": "finnish", "NB": "norsk", "CS": "czech", "SK": "slovak",
    "HU": "magyar", "RO": "romanian", "EL": "greek", "BG": "bulgarian",
    "ET": "estonian", "LV": "latvian", "LT": "lithuanian", "SL": "slovene",
    "ID": "indonesian", "HR": "croatian", "SR": "serbian", "CA": "catalan",
}

# Polyglossia spells a few languages differently than babel.
_POLYGLOSSIA_NAME = {
    "ngerman": "german", "american": "english", "british": "english",
    "brazilian": "portuguese", "magyar": "hungarian", "norsk": "norwegian",
    "slovene": "slovenian",
}

# Every babel option that names a language, needed to tell languages from other options.
_LANGUAGE_OPTIONS = set(_BABEL_FOR_TARGET.values()) | {
    "german", "austrian", "naustrian", "swissgerman", "nswissgerman", "ngermanb",
    "germanb", "english", "UKenglish", "USenglish", "canadian", "australian",
    "newzealand", "francais", "frenchb", "acadian", "canadien", "spanish", "italian",
    "dutch", "afrikaans", "portuges", "brazil", "norwegian", "nynorsk", "hungarian",
    "slovenian", "serbianc", "ukrainian", "russian", "bahasa", "bahasai", "bahasam",
    "malay", "icelandic", "irish", "scottish", "welsh", "basque", "galician",
    "esperanto", "latin", "hebrew", "turkish", "greek", "polutonikogreek",
}

_GERMAN_OPTIONS = {"german", "ngerman", "austrian", "naustrian", "swissgerman", "nswissgerman", "ngermanb", "germanb"}

_OPTIONS_RE = re.compile(r"(\\(?:documentclass|usepackage)[ \t]{0,20}\[)([^\]]{0,500})(\][ \t]{0,20}\{([^}]{0,200})\})")
_POLYGLOSSIA_RE = re.compile(r"\\set(?:default|main)language[ \t]{0,20}(?:\[[^\]]{0,200}\])?[ \t]{0,20}\{(\w{1,40})\}")
_SELECTLANGUAGE_RE = re.compile(r"(\\selectlanguage[ \t]{0,20}\{)(\w{1,40})(\})")


def _swap_language(options: str, target: str) -> tuple[str, str | None]:
    """Replaces the main (last) language in an option list, returns the new list and the old language."""
    parts = options.split(",")
    names = [p.strip() for p in parts]
    main_idx = None
    for idx, name in enumerate(names):
        key, _, value = name.partition("=")
        if key.strip() == "main" and value.strip() in _LANGUAGE_OPTIONS:
            main_idx = idx
            break
        if name in _LANGUAGE_OPTIONS:
            main_idx = idx
    if main_idx is None:
        return options, None
    key, sep, value = names[main_idx].partition("=")
    old = value.strip() if sep else names[main_idx]
    if old == target:
        return options, old
    lead = parts[main_idx][: len(parts[main_idx]) - len(parts[main_idx].lstrip())]
    parts[main_idx] = lead + (f"main={target}" if sep else target)
    kept = [p for idx, p in enumerate(parts) if idx == main_idx or p.strip() != target]
    return ",".join(kept), old


def switch_language(text: str, target_lang: str) -> tuple[str, bool]:
    """Points babel or polyglossia at the target language and reports whether German shorthands were in use."""
    code = (target_lang or "").upper()
    target = _BABEL_FOR_TARGET.get(code) or _BABEL_FOR_TARGET.get(code.split("-")[0])
    old_languages: set[str] = set()

    def options(m: re.Match) -> str:
        package = m.group(4).strip()
        if package not in ("babel",) and not m.group(1).startswith("\\documentclass"):
            return m.group(0)
        found = {o.strip().partition("=")[2].strip() or o.strip() for o in m.group(2).split(",")}
        old_languages.update(found & _LANGUAGE_OPTIONS)
        if target is None:
            return m.group(0)
        new_options, _old = _swap_language(m.group(2), target)
        return m.group(1) + new_options + m.group(3)

    text = _OPTIONS_RE.sub(options, text)

    for m in _POLYGLOSSIA_RE.finditer(text):
        old_languages.add(m.group(1))
    if target is not None:
        poly = _POLYGLOSSIA_NAME.get(target, target)
        text = _POLYGLOSSIA_RE.sub(lambda m: m.group(0)[: m.group(0).index("language") + 8] + "{" + poly + "}", text)
        text = _SELECTLANGUAGE_RE.sub(
            lambda m: m.group(1) + target + m.group(3) if m.group(2) in old_languages else m.group(0), text
        )
    return text, bool(old_languages & _GERMAN_OPTIONS)


# Openers of regions where backslashes and quotes are code and must stay as they are.
_VERBATIM_OPEN_RE = re.compile(
    r"\\begin[ \t]{0,20}\{(verbatim\*?|Verbatim|BVerbatim|lstlisting|minted|comment|filecontents\*?)\}"
    r"|\\verb\*?([^A-Za-z*\s])|\\lstinline(?:\[[^\]\n]{0,200}\])?([^A-Za-z\s\[])"
)

_OPTIONS_END_RE = re.compile(r"\[(?:[^\[\]{}]|\{[^{}]{0,500}\}){0,2000}\]")
_COMBINING = {'"': "\u0308", "'": "\u0301", "`": "\u0300", "^": "\u0302", "~": "\u0303"}
_ACCENT_RE = re.compile(r"\{\\([\"'`^~])\s*\{?([A-Za-z])\}?\}|\\([\"'`^~])\s*\{([A-Za-z])\}|\\([\"'`^~])([A-Za-z])")
_SS_RE = re.compile(r"\{\\ss\}|\\ss\{\}|\\ss(?![A-Za-z])[ \t]?")
_MIDWORD_UMLAUT_RE = re.compile(r'(?<=[A-Za-z])(?<!\\)"([aouAOUs])')
_SHORTHAND_RE = re.compile(r'(?<!\\)"([aouAOUsz`\'<>\-|~="])')
_SHORTHAND_MAP = {
    "a": "ä", "o": "ö", "u": "ü", "A": "Ä", "O": "Ö", "U": "Ü", "s": "ß", "z": "ß",
    "`": "„", "'": "“", "<": "«", ">": "»",
    "-": "", "|": "", '"': "", "~": "-", "=": "-",
}


# Quote commands become characters so the translator can turn them into the target language's quotes.
_QUOTE_CHARS = {"glqq": "„", "grqq": "“", "glq": "‚", "grq": "‘", "flqq": "«", "frqq": "»", "flq": "‹", "frq": "›"}
_QUOTE_RE = re.compile(r"\\(glqq|grqq|glq|grq|flqq|frqq|flq|frq)(?![A-Za-z])(\{\}|\\ |[ \t]*)")


def _accent(mark: str, letter: str) -> str:
    return unicodedata.normalize("NFC", letter + _COMBINING[mark])


def _normalize_plain(text: str, german_shorthands: bool) -> str:
    def accent(m: re.Match) -> str:
        mark = m.group(1) or m.group(3) or m.group(5)
        letter = m.group(2) or m.group(4) or m.group(6)
        return _accent(mark, letter)

    text = _ACCENT_RE.sub(accent, text)
    text = _SS_RE.sub("ß", text)
    text = _QUOTE_RE.sub(lambda m: _QUOTE_CHARS[m.group(1)] + (" " if m.group(2) == "\\ " else ""), text)
    if german_shorthands:
        return _SHORTHAND_RE.sub(lambda m: _SHORTHAND_MAP[m.group(1)], text)
    return _MIDWORD_UMLAUT_RE.sub(lambda m: _SHORTHAND_MAP[m.group(1)], text)


def normalize_accents(text: str, german_shorthands: bool) -> str:
    """Turns accent commands and babel quote shorthands into plain characters so words stay whole."""
    out: list[str] = []
    pos = 0
    while True:
        m = _VERBATIM_OPEN_RE.search(text, pos)
        if m is None:
            break
        # An unclosed region runs to the end, so every opener is searched past at most once.
        keep_from = m.start()
        if m.group(1):
            closer = re.compile(r"\\end[ \t]{0,20}\{" + re.escape(m.group(1)) + r"\}").search(text, m.end())
            end = len(text) if closer is None else closer.end()
            # The options of a listing hold its printed caption, so they are normalized like text.
            options = _OPTIONS_END_RE.match(text, m.end())
            if options:
                keep_from = options.end()
        else:
            delim = m.group(2) or m.group(3)
            k = text.find("}" if delim == "{" else delim, m.end())
            end = len(text) if k == -1 else k + 1
        out.append(_normalize_plain(text[pos:keep_from], german_shorthands))
        out.append(text[keep_from:end])
        pos = end
    out.append(_normalize_plain(text[pos:], german_shorthands))
    return "".join(out)
