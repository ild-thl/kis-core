"""Translates LaTeX by whole paragraphs with markup tags and falls back to pieces where tags get lost."""

import itertools
import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

from src.services.translation import TranslationService
from src.translators.latex_source import fix_inputenc, normalize_accents, switch_language
from src.translators.latex_tags import TAG_RE, translate_tagged


@dataclass(eq=False)
class X:
    """Markup kept as it is, possibly with nested translatable units."""
    content: list


@dataclass(eq=False)
class G:
    """Markup wrapped around words that are translated within their sentence."""
    open: str
    body: list
    close: str


@dataclass(eq=False)
class Unit:
    """One paragraph-like run of text and inline markup that is translated as a whole."""
    parts: list
    tags: dict = field(default_factory=dict)


@dataclass(eq=False)
class _B:
    """Marks an item that ends the current paragraph."""
    item: object


# Argument specs: o optional kept, O optional translated, p mandatory kept, t mandatory translated.
# Mode inline wraps a single translated argument as <g>, nested and block translate arguments separately.
_RULES: dict[str, tuple[str, str]] = {}


def _rule(names: str, spec: str, mode: str) -> None:
    for name in names.split():
        _RULES[name] = (spec, mode)


_rule("textbf textit textsl textsc textsf textrm textup textmd textnormal emph underline uline uuline "
      "uwave sout hl ul enquote mbox fbox textsuperscript textsubscript structure alert only uncover "
      "visible invisible", "t", "inline")
_rule("textcolor colorbox", "opt", "inline")
_rule("fcolorbox", "oppt", "inline")
_rule("href", "pt", "inline")
_rule("hyperref", "ot", "inline")
_rule("makebox framebox", "oot", "inline")
_rule("raisebox", "poot", "inline")
_rule("footnote footnotetext todo", "ot", "nested")
_rule("marginpar marginnote", "Ot", "nested")
_rule("parbox", "ooopt", "nested")
_rule("resizebox", "ppt", "nested")
_rule("scalebox", "pot", "nested")
_rule("rotatebox", "opt", "nested")
_rule("multicolumn", "ppt", "nested")
_rule("multirow", "opopot", "nested")
_rule("cite citep citet citealt citealp citenum citeauthor citeyear citeyearpar parencite textcite "
      "autocite footcite smartcite", "OOp", "nested")
_rule("part chapter section subsection subsubsection paragraph subparagraph addchap addsec "
      "minisec title subtitle frametitle caption subcaption", "Ot", "block")
_rule("captionof", "pOt", "block")
_rule("framesubtitle date", "t", "block")
_rule("author institute", "Op", "block")
_rule("item", "O", "block")
_rule("bibitem", "op", "block")
_rule("maketitle tableofcontents listoffigures listoftables newpage clearpage cleardoublepage par "
      "noindent centering raggedright raggedleft hline toprule midrule bottomrule bigskip medskip "
      "smallskip appendix frontmatter mainmatter backmatter pause printindex", "", "block")
_rule("pagebreak printbibliography", "o", "block")
_rule("vspace", "p", "block")
_rule("includegraphics", "op", "block")
_rule("input include bibliography bibliographystyle cline", "p", "block")
_rule("addbibresource", "op", "block")
_rule("label ref eqref pageref autoref cref Cref vref nameref url nolinkurl path texttt hspace "
      "linespread phantom hphantom vphantom selectlanguage ensuremath hyphenation nocite pagestyle "
      "thispagestyle pagenumbering stepcounter refstepcounter usetikzlibrary tikzset pgfplotsset "
      "lstset hypersetup geometry newgeometry graphicspath includeonly", "p", "inline")
_rule("color", "op", "inline")
_rule("footnotemark", "o", "inline")
_rule("setlength addtolength settowidth settoheight setcounter addtocounter fontsize", "pp", "inline")
_rule("newcounter", "po", "inline")
_rule("rule", "opp", "inline")
_rule("definecolor", "ppp", "inline")
_rule("colorlet", "opp", "inline")
_rule("foreignlanguage", "opp", "inline")
_rule("newcommand renewcommand providecommand", "poop", "inline")
_rule("newenvironment renewenvironment", "poopp", "inline")
_rule("DeclareMathOperator", "pp", "inline")
_rule("lstinputlisting verbatiminput", "op", "block")
_rule("inputminted", "opp", "block")
_rule("includepdf", "op", "block")

_PROTECTED_PREFIXES = ("setbeamer", "usebeamer", "usetheme", "usecolortheme", "usefonttheme",
                       "useinnertheme", "useoutertheme")

_MATH_ENVS = {
    "equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*",
    "eqnarray", "eqnarray*", "math", "displaymath", "flalign", "flalign*", "alignat", "alignat*",
}
# Kept as written because printed text there is rare and mistakes would break compilation.
_PROTECTED_ENVS = {
    "verbatim", "verbatim*", "Verbatim", "BVerbatim", "lstlisting", "minted", "comment",
    "filecontents", "filecontents*", "tikzpicture", "pgfpicture", "circuitikz", "forest",
    "algorithmic", "tikzcd", "dot2tex",
}
_ENV_ARGS = {
    "tabular": "op", "tabular*": "pop", "tabularx": "pop", "tabulary": "pop", "longtable": "op",
    "array": "op", "minipage": "ooop", "figure": "o", "figure*": "o", "table": "o", "table*": "o",
    "wrapfigure": "opop", "wraptable": "opop", "subfigure": "op", "multicols": "pO",
    "multicols*": "pO", "itemize": "o", "enumerate": "o", "description": "o", "frame": "ott",
    "block": "t", "alertblock": "t", "exampleblock": "t", "column": "op", "columns": "o",
    "thebibliography": "p", "otherlanguage": "p", "otherlanguage*": "p", "tcolorbox": "o",
    "mdframed": "o", "adjustbox": "p", "spacing": "p",
}
# Commands inside formulas whose argument is printed as text.
_TEXT_IN_MATH_RE = re.compile(r"\\(text|textrm|textnormal|textup|textit|textbf|textsf|mbox|intertext|shortintertext)\s*\{")
_CAPTION_NAMES = {
    "\\figurename", "\\tablename", "\\contentsname", "\\listfigurename", "\\listtablename",
    "\\refname", "\\bibname", "\\indexname", "\\chaptername", "\\partname", "\\abstractname",
    "\\appendixname", "\\proofname", "\\lstlistingname", "\\lstlistlistingname",
}
_PREAMBLE_RE = re.compile(r"\\(title|subtitle|date|newtheorem|renewcommand)(?![A-Za-z])")
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n\s*")
_STRUCTURE_RE = re.compile(r"\\(?:begin|item|par)(?![A-Za-z])")
_BRACE_TOKEN_RE = re.compile(r"\\.|%[^\n]*\n?|[{}]", re.DOTALL)
_BRACKET_TOKEN_RE = re.compile(r"\\.|[\[\]]", re.DOTALL)
_TEXT_LETTER_RE = re.compile(r"\\[A-Za-z]+|\\.|([^\W\d_])", re.DOTALL)
_DIMENSION_RE = re.compile(r"\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)\s*\\?[A-Za-z]{0,10}\s*")
_BREAK_ARG_RE = re.compile(r"\s{0,20}\[" + _DIMENSION_RE.pattern + r"\]")
_OVERLAY_RE = re.compile(r"<[^<>\n]{1,20}>")
_ACCENT_CHARS = "\"'`^~=."
# Deeper nesting is kept as written, which bounds the work per character.
_MAX_DEPTH = 40


class _Doc:
    """The whole document with bracket pairs, comments and letters looked up once."""

    def __init__(self, text: str):
        self.text = text
        self.braces: dict[int, int] = {}
        self.comments: list[tuple[int, int]] = []
        stack: list[int] = []
        for m in _BRACE_TOKEN_RE.finditer(text):
            token = m.group(0)
            if token == "{":
                stack.append(m.start())
            elif token == "}":
                if stack:
                    self.braces[stack.pop()] = m.start()
            elif token[0] == "%":
                self.comments.append((m.start(), m.end()))
        self.comment_starts = [start for start, _end in self.comments]
        self.brackets: dict[int, int] = {}
        stack = []
        for m in _BRACKET_TOKEN_RE.finditer(text):
            if m.group(0) == "[":
                stack.append(m.start())
            elif m.group(0) == "]" and stack:
                self.brackets[stack.pop()] = m.start()
        self.blanks = [m.start() for m in _BLANK_LINE_RE.finditer(text)]
        self.structures = [m.start() for m in _STRUCTURE_RE.finditer(text)]
        self.letters = [m.start(1) for m in _TEXT_LETTER_RE.finditer(text) if m.group(1)]

    def group_end(self, start: int, hi: int, open_ch: str = "{") -> int | None:
        """End after the closing bracket of the group opening at start, None when it does not close before hi."""
        if start >= hi or self.text[start] != open_ch:
            return None
        close = (self.braces if open_ch == "{" else self.brackets).get(start)
        return None if close is None or close >= hi else close + 1

    @staticmethod
    def _any_in(positions: list[int], a: int, b: int) -> bool:
        idx = bisect_left(positions, a)
        return idx < len(positions) and positions[idx] < b

    def has_letters(self, a: int, b: int) -> bool:
        return self._any_in(self.letters, a, b)

    def inline_safe(self, a: int, b: int) -> bool:
        return not self._any_in(self.blanks, a, b) and not self._any_in(self.structures, a, b)

    def in_comment(self, idx: int) -> bool:
        k = bisect_right(self.comment_starts, idx) - 1
        return k >= 0 and self.comments[k][0] < idx < self.comments[k][1]


@dataclass
class _Ctx:
    doc: _Doc
    theorems: set = field(default_factory=lambda: {"proof"})
    depth: int = 0


def _is_escaped(text: str, idx: int) -> bool:
    n = 0
    j = idx - 1
    while j >= 0 and text[j] == "\\":
        n += 1
        j -= 1
    return n % 2 == 1


def _skip_space(text: str, i: int, hi: int) -> int:
    """Skips spaces and at most one line break, like TeX between arguments."""
    j = i
    newlines = 0
    while j < hi and text[j] in " \t\n":
        if text[j] == "\n":
            newlines += 1
            if newlines > 1:
                return i
        j += 1
    return j


def _has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in TAG_RE.sub("", re.sub(r"\\[A-Za-z]+", "", text)))


def _textlike(text: str) -> bool:
    """Guesses whether an argument of an unknown command is readable text."""
    stripped = text.strip()
    if "=" in stripped or not _has_letters(stripped):
        return False
    if re.search(r"\s", stripped):
        return True
    # A single long token is an identifier or data, not prose.
    if len(stripped) > 60 or _DIMENSION_RE.fullmatch(stripped):
        return False
    return not re.fullmatch(r"[\w.:/#-]*\d[\w.:/#-]*|\S*[/.:]\S*", stripped)


def _find_env_end(text: str, start: int, hi: int, env: str) -> int:
    m = re.compile(r"\\end\s*\{" + re.escape(env) + r"\}").search(text, start, hi)
    return hi if m is None else m.end()


def _find_math_end(text: str, start: int, hi: int, delim: str) -> int:
    i = start
    while True:
        i = text.find(delim, i, hi)
        if i == -1:
            return hi
        if not _is_escaped(text, i):
            return i + len(delim)
        i += 1


def _math(a: int, b: int, ctx: _Ctx) -> X:
    """Keeps a formula and translates only the words inside \\text and similar."""
    text = ctx.doc.text
    content: list = []
    pos = a
    for m in _TEXT_IN_MATH_RE.finditer(text, a, b):
        if m.start() < pos or _is_escaped(text, m.start()):
            continue
        end = ctx.doc.group_end(m.end() - 1, b)
        if end is None:
            continue
        inner = text[m.end():end - 1]
        letters = sum(ch.isalpha() for ch in inner)
        if not (re.search(r"[^\W\d_]{2,}\s+[^\W\d_]", inner) or letters >= 4):
            continue
        content.append(text[pos:m.end()])
        content.extend(_block(m.end(), end - 1, ctx))
        content.append("}")
        pos = end
    content.append(text[pos:b])
    return X(content)


def _take_args(doc: _Doc, pos: int, hi: int, spec: str) -> tuple[list[tuple[str, str, int, int]], int]:
    """Reads the arguments a spec names, returns (kind, leading space, start, end) and the end."""
    text = doc.text
    args: list[tuple[str, str, int, int]] = []
    for kind in spec:
        j = _skip_space(text, pos, hi)
        if kind in "oOU":
            end = doc.group_end(j, hi, "[")
            if end is not None:
                args.append((kind, text[pos:j], j, end))
                pos = end
            continue
        end = doc.group_end(j, hi, "{")
        if end is not None:
            args.append((kind, text[pos:j], j, end))
            pos = end
        elif kind == "p" and j + 1 < hi and text[j] == "\\":
            m = re.compile(r"\\([A-Za-z]+|.)", re.DOTALL).match(text, j, hi)
            args.append((kind, text[pos:j], j, m.end()))
            pos = m.end()
        else:
            break
    return args, pos


def _translatable(doc: _Doc, kind: str, a: int, b: int) -> bool:
    if doc.text[a] not in "[{":
        return False
    if kind in "tO":
        return doc.has_letters(a + 1, b - 1)
    if kind == "U":
        inner = doc.text[a + 1:b - 1]
        return _textlike(inner) and bool(re.search(r"\s", inner.strip()))
    return False


def _command_item(head: str, args: list, mode: str, ctx: _Ctx):
    """Builds the item for a command from its head and parsed arguments."""
    doc = ctx.doc
    text = doc.text
    marks = [_translatable(doc, kind, a, b) for kind, _ws, a, b in args]
    if mode == "inline" and sum(marks) == 1:
        idx = marks.index(True)
        kind, ws, a, b = args[idx]
        if kind == "t" and doc.inline_safe(a + 1, b - 1):
            open_ = head + "".join(w + text[x:y] for _k, w, x, y in args[:idx]) + ws + "{"
            close = "}" + "".join(w + text[x:y] for _k, w, x, y in args[idx + 1:])
            return G(open_, _inline(a + 1, b - 1, ctx), close)
    content: list = [head]
    for (kind, ws, a, b), mark in zip(args, marks):
        content.append(ws)
        if mark:
            content.append(text[a])
            content.extend(_block(a + 1, b - 1, ctx))
            content.append(text[b - 1])
        else:
            content.append(text[a:b])
    return X(content)


def _scan(lo: int, hi: int, ctx: _Ctx) -> list:
    """Splits LaTeX into text, inline markup and paragraph-ending items."""
    doc = ctx.doc
    text = doc.text
    items: list = []
    buf: list[str] = []

    def emit(obj, boundary: bool = False) -> None:
        if buf:
            items.append("".join(buf))
            buf.clear()
        items.append(_B(obj) if boundary else obj)

    i = lo
    while i < hi:
        ch = text[i]
        if ch == "%":
            nl = text.find("\n", i, hi)
            end = hi if nl == -1 else nl + 1
            emit(text[i:end], boundary=True)
            i = end
            continue
        if ch == "\n":
            m = _BLANK_LINE_RE.match(text, i, hi)
            if m:
                emit(m.group(0), boundary=True)
                i = m.end()
                continue
        if ch == "$":
            delim = "$$" if text.startswith("$$", i) else "$"
            end = _find_math_end(text, i + len(delim), hi, delim)
            emit(_math(i, end, ctx))
            i = end
            continue
        if ch == "~":
            emit(X(["~"]))
            i += 1
            continue
        if ch == "&":
            emit("&", boundary=True)
            i += 1
            continue
        if ch == "{":
            end = doc.group_end(i, hi)
            if end is not None and not doc.has_letters(i + 1, end - 1):
                emit(X([text[i:end]]))
                i = end
            elif end is not None and doc.inline_safe(i + 1, end - 1):
                emit(G("{", _inline(i + 1, end - 1, ctx), "}"))
                i = end
            else:
                emit("{", boundary=True)
                i += 1
            continue
        if ch == "}":
            emit("}", boundary=True)
            i += 1
            continue
        if ch == "\\":
            i = _command(i, hi, ctx, emit, buf)
            continue
        buf.append(ch)
        i += 1
    if buf:
        items.append("".join(buf))
    return items


def _command(i: int, hi: int, ctx: _Ctx, emit, buf: list) -> int:
    """Handles one backslash command and returns the position after it."""
    doc = ctx.doc
    text = doc.text
    j = i + 1
    if j >= hi:
        emit(X(["\\"]))
        return hi
    c = text[j]
    if not c.isalpha():
        if c in "%&#_${}":
            buf.append(c)
            return j + 1
        if c == "-":
            return j + 1
        if c in " \n":
            buf.append(" ")
            return j + 1
        if c in "([":
            closing = "\\)" if c == "(" else "\\]"
            end = text.find(closing, j + 1, hi)
            end = hi if end == -1 else end + 2
            emit(_math(i, end, ctx))
            return end
        if c == "\\":
            k = j + 1
            if k < hi and text[k] == "*":
                k += 1
            m = _BREAK_ARG_RE.match(text, k, hi)
            if m:
                k = m.end()
            emit(text[i:k], boundary=True)
            return k
        k = j + 1
        if c in _ACCENT_CHARS and k < hi:
            end = doc.group_end(k, hi)
            k = end if end is not None else (k + 1 if text[k].isalpha() else k)
        emit(X([text[i:k]]))
        return k

    k = j
    while k < hi and text[k].isalpha():
        k += 1
    name = text[j:k]

    if name in ("verb", "lstinline", "mintinline"):
        p = k + 1 if k < hi and text[k] == "*" else k
        if name == "lstinline":
            p = doc.group_end(p, hi, "[") or p
        if name == "mintinline":
            p = doc.group_end(p, hi, "[") or p
            p = doc.group_end(p, hi, "{") or p
        if p < hi and text[p] == "{":
            end = doc.group_end(p, hi) or hi
        elif p < hi:
            close = text.find(text[p], p + 1, hi)
            end = hi if close == -1 else close + 1
        else:
            end = hi
        emit(X([text[i:end]]))
        return end

    if name in ("begin", "end"):
        p = _skip_space(text, k, hi)
        end = doc.group_end(p, hi)
        if end is None:
            emit(X([text[i:k]]))
            return k
        env = text[p + 1:end - 1].strip()
        if name == "end":
            emit(text[i:end], boundary=True)
            return end
        if env in _PROTECTED_ENVS:
            stop = _find_env_end(text, end, hi, env)
            emit(text[i:stop], boundary=True)
            return stop
        if env in _MATH_ENVS:
            stop = _find_env_end(text, end, hi, env)
            emit(_math(i, stop, ctx))
            return stop
        head_end = end
        m = _OVERLAY_RE.match(text, head_end, hi)
        if m:
            head_end = m.end()
        spec = "O" if env in ctx.theorems else _ENV_ARGS.get(env, "U")
        args, stop = _take_args(doc, head_end, hi, spec)
        emit(_command_item(text[i:head_end], args, "block", ctx), boundary=True)
        return stop

    head_end = k
    if head_end < hi and text[head_end] == "*":
        head_end += 1
    m = _OVERLAY_RE.match(text, head_end, hi)
    if m and (name in _RULES or m.group(0)[1:2].isdigit()):
        head_end = m.end()
    head = text[i:head_end]

    if name in _RULES:
        spec, mode = _RULES[name]
        args, stop = _take_args(doc, head_end, hi, spec)
        emit(_command_item(head, args, mode, ctx), boundary=(mode == "block"))
        return stop

    args, stop = _unknown_args(doc, head_end, hi)
    if name.startswith(_PROTECTED_PREFIXES):
        emit(X([head] + [ws + text[a:b] for _k, ws, a, b in args]))
        return stop
    args = [
        (("t" if _textlike(text[a + 1:b - 1]) else "p") if text[a] == "{" else "o", ws, a, b)
        for _k, ws, a, b in args
    ]
    emit(_command_item(head, args, "inline", ctx))
    return stop


def _unknown_args(doc: _Doc, pos: int, hi: int) -> tuple[list[tuple[str, str, int, int]], int]:
    """Takes directly attached optional arguments and following brace groups of an unknown command."""
    text = doc.text
    args: list[tuple[str, str, int, int]] = []
    while True:
        end = doc.group_end(pos, hi, "[")
        if end is None:
            break
        args.append(("o", "", pos, end))
        pos = end
    while True:
        j = pos
        while j < hi and text[j] in " \t":
            j += 1
        end = doc.group_end(j, hi)
        if end is None:
            break
        args.append(("p", text[pos:j], j, end))
        pos = end
    return args, pos


def _inline(a: int, b: int, ctx: _Ctx) -> list:
    """Parses text that stays inside one sentence, paragraph breaks become kept markup."""
    if ctx.depth >= _MAX_DEPTH:
        return [X([ctx.doc.text[a:b]])]
    ctx.depth += 1
    try:
        items = _scan(a, b, ctx)
    finally:
        ctx.depth -= 1
    out: list = []
    for item in items:
        if isinstance(item, _B):
            inner = item.item
            out.append(inner if isinstance(inner, X) else X([inner]))
        else:
            out.append(item)
    return out


def _is_edge(item) -> bool:
    return isinstance(item, X) or (isinstance(item, str) and not item.strip())


def _block(a: int, b: int, ctx: _Ctx) -> list:
    """Parses LaTeX into kept markup and translatable units, one per paragraph-like run."""
    if ctx.depth >= _MAX_DEPTH:
        return [ctx.doc.text[a:b]]
    out: list = []
    current: list = []

    def flush() -> None:
        lead: list = []
        trail: list = []
        start = 0
        while start < len(current) and _is_edge(current[start]):
            start += 1
        stop = len(current)
        while stop > start and _is_edge(current[stop - 1]):
            stop -= 1
        lead = current[:start]
        trail = current[stop:]
        middle = current[start:stop]
        if middle and isinstance(middle[0], str):
            s = middle[0]
            lead.append(s[: len(s) - len(s.lstrip())])
            middle[0] = s.lstrip()
        if middle and isinstance(middle[-1], str):
            s = middle[-1]
            trail.insert(0, s[len(s.rstrip()):])
            middle[-1] = s.rstrip()
        out.extend(lead)
        if middle:
            out.append(Unit(middle))
        out.extend(trail)
        current.clear()

    ctx.depth += 1
    try:
        items = _scan(a, b, ctx)
    finally:
        ctx.depth -= 1
    for item in items:
        if isinstance(item, _B):
            flush()
            out.append(item.item)
        else:
            current.append(item)
    flush()
    return out


def _preamble(hi: int, ctx: _Ctx) -> list:
    """Keeps the preamble and translates only titles, theorem names and caption names."""
    doc = ctx.doc
    text = doc.text
    out: list = []
    pos = 0
    for m in _PREAMBLE_RE.finditer(text, 0, hi):
        if m.start() < pos or _is_escaped(text, m.start()) or doc.in_comment(m.start()):
            continue
        name = m.group(1)
        head_end = m.end() + (1 if text[m.end():m.end() + 1] == "*" else 0)
        if name == "newtheorem":
            args, stop = _take_args(doc, head_end, hi, "poto")
            if args and text[args[0][2]] == "{":
                ctx.theorems.add(text[args[0][2] + 1:args[0][3] - 1].strip())
        elif name == "renewcommand":
            args, stop = _take_args(doc, head_end, hi, "pot")
            first = text[args[0][2]:args[0][3]].strip("{}").strip() if args else ""
            if first not in _CAPTION_NAMES:
                continue
        else:
            args, stop = _take_args(doc, head_end, hi, "t" if name == "date" else "Ot")
        out.append(text[pos:m.start()])
        out.append(_command_item(text[m.start():head_end], args, "block", ctx))
        pos = stop
    out.append(text[pos:hi])
    return out


def _units(items: list) -> list[Unit]:
    found: list[Unit] = []
    for item in items:
        if isinstance(item, Unit):
            found.append(item)
            for part in item.parts:
                found.extend(_units_in_part(part))
        elif isinstance(item, X):
            found.extend(_units(item.content))
    return found


def _units_in_part(part) -> list[Unit]:
    if isinstance(part, X):
        return _units(part.content)
    if isinstance(part, G):
        return [u for p in part.body for u in _units_in_part(p)]
    return []


def _serialize(unit: Unit) -> str:
    counter = itertools.count(1)

    def ser(parts: list) -> str:
        out: list[str] = []
        for p in parts:
            if isinstance(p, str):
                out.append(re.sub(r"\s+", " ", p))
            elif isinstance(p, X):
                key = f"x{next(counter)}"
                unit.tags[key] = p
                out.append(f"<{key}/>")
            else:
                key = f"g{next(counter)}"
                unit.tags[key] = p
                out.append(f"<{key}>{ser(p.body)}</{key}>")
        return "".join(out)

    return ser(unit.parts)


_ESCAPES = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "%": r"\%", "&": r"\&", "#": r"\#",
    "_": r"\_", "$": r"\$", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    "\u00a0": "~", "\u202f": r"\,", "\u2009": r"\,", "\u200b": "", "\u00ad": "", "\ufeff": "",
}
_ESCAPE_RE = re.compile("|".join(re.escape(k) for k in _ESCAPES))


def _escape(text: str) -> str:
    return _ESCAPE_RE.sub(lambda m: _ESCAPES[m.group(0)], text)


def _text_runs(parts: list) -> list[str]:
    """Text pieces with letters in reading order, used by the piece-by-piece fallback."""
    runs: list[str] = []
    for p in parts:
        if isinstance(p, str):
            if _has_letters(p):
                runs.append(p)
        elif isinstance(p, G):
            runs.extend(_text_runs(p.body))
    return runs


class _Renderer:
    def __init__(self, tagged: dict, pieces: dict):
        self.tagged = tagged
        self.pieces = pieces

    def items(self, items: list) -> str:
        out: list[str] = []
        for item in items:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, X):
                out.append(self.items(item.content))
            elif isinstance(item, Unit):
                out.append(self.unit(item))
        return "".join(out)

    def unit(self, unit: Unit) -> str:
        tagged = self.tagged.get(id(unit))
        if tagged is not None:
            return self.from_tags(unit, tagged)
        return self.parts(unit.parts, iter(self.pieces.get(id(unit), [])))

    def from_tags(self, unit: Unit, translated: str) -> str:
        out: list[str] = []
        pos = 0
        for m in TAG_RE.finditer(translated):
            out.append(_escape(translated[pos:m.start()]))
            obj = unit.tags[m.group(2) + m.group(3)]
            if isinstance(obj, X):
                out.append(self.items(obj.content))
            else:
                out.append(obj.close if m.group(1) else obj.open)
            pos = m.end()
        out.append(_escape(translated[pos:]))
        return "".join(out)

    def parts(self, parts: list, pieces) -> str:
        out: list[str] = []
        for p in parts:
            if isinstance(p, str):
                if _has_letters(p):
                    piece = next(pieces, None)
                    if piece is not None:
                        lead = p[: len(p) - len(p.lstrip())]
                        trail = p[len(p.rstrip()):]
                        p = lead + piece.strip() + trail
                out.append(_escape(p))
            elif isinstance(p, X):
                out.append(self.items(p.content))
            else:
                out.append(p.open + self.parts(p.body, pieces) + p.close)
        return "".join(out)


def _parse(text: str, target_lang: str) -> tuple[list, list[Unit]]:
    """Prepares the source and returns the template and the units worth translating."""
    text = fix_inputenc(text)
    text, german_shorthands = switch_language(text, target_lang)
    text = normalize_accents(text, german_shorthands)

    ctx = _Ctx(doc=_Doc(text))
    body_start = 0
    for m in re.finditer(r"\\begin\s*\{document\}", text):
        if not ctx.doc.in_comment(m.start()):
            body_start = m.start()
            break
    template = _preamble(body_start, ctx) + _block(body_start, len(text), ctx)
    units = [u for u in _units(template) if _text_runs(u.parts)]
    return template, units


def translatable_text(text: str) -> str:
    """The text that will go to the translator, one unit per line, used for the length limit."""
    _template, units = _parse(text, "")
    return "\n".join(TAG_RE.sub("", _serialize(u)) for u in units)


def translate_latex_preserve_structure(
    text: str, source_lang: str, target_lang: str, service: TranslationService
) -> str:
    if not text or not text.strip():
        return text

    template, units = _parse(text, target_lang)
    tagged_texts = [_serialize(u) for u in units]
    translated = translate_tagged(tagged_texts, source_lang, target_lang, service)

    tagged: dict = {}
    failed: list[Unit] = []
    for unit, result in zip(units, translated):
        if result is None:
            failed.append(unit)
        else:
            tagged[id(unit)] = result

    pieces: dict = {}
    runs = [(u, r) for u in failed for r in _text_runs(u.parts)]
    if runs:
        answers = service.translate_batch([r.strip() for _u, r in runs], source_lang, target_lang)
        for (unit, _run), answer in zip(runs, answers):
            pieces.setdefault(id(unit), []).append(answer)

    return _Renderer(tagged, pieces).items(template)
