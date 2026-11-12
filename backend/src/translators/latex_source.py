"""Reads a LaTeX file in any common encoding and adapts its preamble to UTF-8 and the target language."""

import re
import unicodedata
from pathlib import Path

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

_INPUTENC_BYTES_RE = re.compile(rb"\\usepackage\s*\[([^\]]*)\]\s*\{inputenc\}")
_INPUTENC_RE = re.compile(r"(\\usepackage\s*\[)([^\]]*)(\]\s*\{inputenc\})")


def decode_tex(raw: bytes) -> str:
    """Decodes UTF-8 first, then the encoding the file declares, then Windows-1252 and Latin-1."""
    if b"\x00" in raw:
        raise ValueError("binary content")
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return raw.decode("utf-8")
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
            return raw.decode(codec)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def tex_plain_text(path: str | Path) -> str:
    """Plain text of a LaTeX file in any encoding, used for the length check."""
    from src.utils.text_extraction import extract_text_tex
    return extract_text_tex(decode_tex(Path(path).read_bytes()).encode("utf-8"))


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

_OPTIONS_RE = re.compile(r"(\\(?:documentclass|usepackage)\s*\[)([^\]]*)(\]\s*\{([^}]*)\})")
_POLYGLOSSIA_RE = re.compile(r"\\set(?:default|main)language\s*(?:\[[^\]]*\])?\s*\{(\w+)\}")
_SELECTLANGUAGE_RE = re.compile(r"(\\selectlanguage\s*\{)(\w+)(\})")


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


# Regions where backslashes and quotes are code and must stay as they are.
_VERBATIM_RE = re.compile(
    r"\\begin\s*\{(verbatim\*?|Verbatim|BVerbatim|lstlisting|minted|comment|filecontents\*?)\}.*?\\end\s*\{\1\}"
    r"|\\verb\*?(.).*?\2|\\lstinline(?:\[[^\]]*\])?(?:\{[^}]*\}|(.).*?\3)",
    re.DOTALL,
)

_COMBINING = {'"': "\u0308", "'": "\u0301", "`": "\u0300", "^": "\u0302", "~": "\u0303"}
_ACCENT_RE = re.compile(r"\{\\([\"'`^~])\s*\{?([A-Za-z])\}?\}|\\([\"'`^~])\s*\{([A-Za-z])\}|\\([\"'`^~])([A-Za-z])")
_SS_RE = re.compile(r"\{\\ss\}|\\ss\{\}|\\ss(?![A-Za-z])[ \t]?")
_MIDWORD_UMLAUT_RE = re.compile(r'(?<=[A-Za-z])(?<!\\)"([aouAOUs])')
_SHORTHAND_RE = re.compile(r'(?<!\\)"([aouAOUsz`\'<>\-|~="])')
_SHORTHAND_MAP = {
    "a": "ä", "o": "ö", "u": "ü", "A": "Ä", "O": "Ö", "U": "Ü", "s": "ß", "z": "ß",
    "`": r"\glqq{}", "'": r"\grqq{}", "<": r"\flqq{}", ">": r"\frqq{}",
    "-": "", "|": "", '"': "", "~": "-", "=": "-",
}


def _accent(mark: str, letter: str) -> str:
    return unicodedata.normalize("NFC", letter + _COMBINING[mark])


def _normalize_plain(text: str, german_shorthands: bool) -> str:
    def accent(m: re.Match) -> str:
        mark = m.group(1) or m.group(3) or m.group(5)
        letter = m.group(2) or m.group(4) or m.group(6)
        return _accent(mark, letter)

    text = _ACCENT_RE.sub(accent, text)
    text = _SS_RE.sub("ß", text)
    if german_shorthands:
        return _SHORTHAND_RE.sub(lambda m: _SHORTHAND_MAP[m.group(1)], text)
    return _MIDWORD_UMLAUT_RE.sub(lambda m: _SHORTHAND_MAP[m.group(1)], text)


def normalize_accents(text: str, german_shorthands: bool) -> str:
    """Turns accent commands and babel quote shorthands into plain characters so words stay whole."""
    out: list[str] = []
    pos = 0
    for m in _VERBATIM_RE.finditer(text):
        out.append(_normalize_plain(text[pos:m.start()], german_shorthands))
        out.append(m.group(0))
        pos = m.end()
    out.append(_normalize_plain(text[pos:], german_shorthands))
    return "".join(out)
