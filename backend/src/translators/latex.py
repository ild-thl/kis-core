"""Translates LaTeX by whole paragraphs with markup tags and falls back to pieces where tags get lost."""

import itertools
import re
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
# Kept as written because printed text there is rare and mistakes would break compilation.
_TEXT_IN_MATH_RE = re.compile(r"\\(text|textrm|textnormal|textup|textit|textbf|textsf|mbox|intertext|shortintertext)\s*\{")
_CAPTION_NAMES = {
    "\\figurename", "\\tablename", "\\contentsname", "\\listfigurename", "\\listtablename",
    "\\refname", "\\bibname", "\\indexname", "\\chaptername", "\\partname", "\\abstractname",
    "\\appendixname", "\\proofname", "\\lstlistingname", "\\lstlistlistingname",
}
_PREAMBLE_RE = re.compile(r"\\(title|subtitle|date|newtheorem|renewcommand)(?![A-Za-z])")
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n\s*")
_DIMENSION_RE = re.compile(r"\s*[-+]?\d*\.?\d+\s*\\?[A-Za-z]{0,10}\s*")
_OVERLAY_RE = re.compile(r"<[^<>\n]{1,20}>")
_ACCENT_CHARS = "\"'`^~=."


@dataclass
class _Ctx:
    theorems: set = field(default_factory=lambda: {"proof"})


def _is_escaped(text: str, idx: int) -> bool:
    n = 0
    j = idx - 1
    while j >= 0 and text[j] == "\\":
        n += 1
        j -= 1
    return n % 2 == 1


def _read_group(text: str, start: int, open_ch: str, close_ch: str) -> tuple[str | None, int]:
    if start >= len(text) or text[start] != open_ch:
        return None, start
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1], i + 1
        elif ch == "%" and open_ch == "{":
            nl = text.find("\n", i)
            i = len(text) if nl == -1 else nl + 1
            continue
        i += 1
    return None, start


def _skip_space(text: str, i: int) -> int:
    """Skips spaces and at most one line break, like TeX between arguments."""
    j = i
    newlines = 0
    while j < len(text) and text[j] in " \t\n":
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
    if not _has_letters(stripped) or "=" in stripped or _DIMENSION_RE.fullmatch(stripped):
        return False
    if re.fullmatch(r"[\w.:/#-]*\d[\w.:/#-]*|\S*[/.:]\S*", stripped):
        return False
    return True


def _inline_safe(text: str) -> bool:
    return not _BLANK_LINE_RE.search(text) and not re.search(r"\\(begin|item|par)(?![A-Za-z])", text)


def _find_env_end(text: str, start: int, env: str) -> int:
    m = re.compile(r"\\end\s*\{" + re.escape(env) + r"\}").search(text, start)
    return len(text) if m is None else m.end()


def _find_math_end(text: str, start: int, delim: str) -> int:
    i = start
    while i < len(text):
        if text.startswith(delim, i) and not _is_escaped(text, i):
            return i + len(delim)
        i += 1
    return len(text)


def _math(src: str, ctx: _Ctx) -> X:
    """Keeps a formula and translates only the words inside \\text and similar."""
    content: list = []
    pos = 0
    for m in _TEXT_IN_MATH_RE.finditer(src):
        if m.start() < pos or _is_escaped(src, m.start()):
            continue
        group, end = _read_group(src, m.end() - 1, "{", "}")
        if group is None:
            continue
        inner = group[1:-1]
        letters = sum(ch.isalpha() for ch in inner)
        if not (re.search(r"[^\W\d_]{2,}\s+[^\W\d_]", inner) or letters >= 4):
            continue
        content.append(src[pos:m.end()])
        content.extend(_block(inner, ctx))
        content.append("}")
        pos = end
    content.append(src[pos:])
    return X(content)


def _take_args(text: str, pos: int, spec: str) -> tuple[list[tuple[str, str, str]], int]:
    """Reads the arguments a spec names, returns (kind, leading space, group) and the end."""
    args: list[tuple[str, str, str]] = []
    for kind in spec:
        j = _skip_space(text, pos)
        if kind in "oOU":
            if j < len(text) and text[j] == "[":
                group, end = _read_group(text, j, "[", "]")
                if group is not None:
                    args.append((kind, text[pos:j], group))
                    pos = end
            continue
        if j < len(text) and text[j] == "{":
            group, end = _read_group(text, j, "{", "}")
            if group is None:
                break
            args.append((kind, text[pos:j], group))
            pos = end
        elif kind == "p" and j < len(text) and text[j] == "\\":
            m = re.compile(r"\\([A-Za-z]+|.)").match(text, j)
            args.append((kind, text[pos:j], m.group(0)))
            pos = m.end()
        else:
            break
    return args, pos


def _translatable(kind: str, group: str) -> bool:
    inner = group[1:-1] if group[:1] in "[{" else ""
    if kind in "tO":
        return _has_letters(inner)
    if kind == "U":
        return _textlike(inner) and bool(re.search(r"\s", inner.strip()))
    return False


def _command_item(head: str, args: list, mode: str, ctx: _Ctx):
    """Builds the item for a command from its head and parsed arguments."""
    marks = [_translatable(kind, group) for kind, _ws, group in args]
    if mode == "inline" and sum(marks) == 1:
        idx = marks.index(True)
        kind, ws, group = args[idx]
        if kind == "t" and _inline_safe(group[1:-1]):
            open_ = head + "".join(w + g for _k, w, g in args[:idx]) + ws + "{"
            close = "}" + "".join(w + g for _k, w, g in args[idx + 1:])
            return G(open_, _inline(group[1:-1], ctx), close)
    content: list = [head]
    for (kind, ws, group), mark in zip(args, marks):
        content.append(ws)
        if mark:
            content.append(group[0])
            content.extend(_block(group[1:-1], ctx))
            content.append(group[-1])
        else:
            content.append(group)
    return X(content)


def _scan(text: str, ctx: _Ctx) -> list:
    """Splits LaTeX into text, inline markup and paragraph-ending items."""
    items: list = []
    buf: list[str] = []

    def emit(obj, boundary: bool = False) -> None:
        if buf:
            items.append("".join(buf))
            buf.clear()
        items.append(_B(obj) if boundary else obj)

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "%":
            nl = text.find("\n", i)
            end = n if nl == -1 else nl + 1
            emit(text[i:end], boundary=True)
            i = end
            continue
        if ch == "\n":
            m = _BLANK_LINE_RE.match(text, i)
            if m:
                emit(m.group(0), boundary=True)
                i = m.end()
                continue
        if ch == "$":
            delim = "$$" if text.startswith("$$", i) else "$"
            end = _find_math_end(text, i + len(delim), delim)
            emit(_math(text[i:end], ctx))
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
            group, end = _read_group(text, i, "{", "}")
            if group is not None and not _has_letters(group[1:-1]):
                emit(X([group]))
                i = end
            elif group is not None and _inline_safe(group[1:-1]):
                emit(G("{", _inline(group[1:-1], ctx), "}"))
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
            i = _command(text, i, ctx, emit, buf)
            continue
        buf.append(ch)
        i += 1
    if buf:
        items.append("".join(buf))
    return items


def _command(text: str, i: int, ctx: _Ctx, emit, buf: list) -> int:
    """Handles one backslash command and returns the position after it."""
    n = len(text)
    j = i + 1
    if j >= n:
        emit(X(["\\"]))
        return n
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
            end = text.find(closing, j + 1)
            end = n if end == -1 else end + 2
            emit(_math(text[i:end], ctx))
            return end
        if c == "\\":
            k = j + 1
            if k < n and text[k] == "*":
                k += 1
            m = re.compile(r"\s*\[" + _DIMENSION_RE.pattern + r"\]").match(text, k)
            if m:
                k = m.end()
            emit(text[i:k], boundary=True)
            return k
        k = j + 1
        if c in _ACCENT_CHARS and k < n:
            group, end = _read_group(text, k, "{", "}")
            k = end if group is not None else (k + 1 if text[k].isalpha() else k)
        emit(X([text[i:k]]))
        return k

    k = j
    while k < n and text[k].isalpha():
        k += 1
    name = text[j:k]

    if name in ("verb", "lstinline", "mintinline"):
        p = k + 1 if k < n and text[k] == "*" else k
        if name == "lstinline":
            group, end = _read_group(text, p, "[", "]")
            p = end if group else p
        if name == "mintinline":
            for open_ch, close_ch in (("[", "]"), ("{", "}")):
                group, end = _read_group(text, p, open_ch, close_ch)
                p = end if group else p
        if p < n and text[p] == "{":
            _group, end = _read_group(text, p, "{", "}")
        elif p < n:
            close = text.find(text[p], p + 1)
            end = n if close == -1 else close + 1
        else:
            end = n
        emit(X([text[i:end]]))
        return end

    if name in ("begin", "end"):
        p = _skip_space(text, k)
        group, end = _read_group(text, p, "{", "}")
        if group is None:
            emit(X([text[i:k]]))
            return k
        env = group[1:-1].strip()
        if name == "end":
            emit(text[i:end], boundary=True)
            return end
        if env in _PROTECTED_ENVS:
            stop = _find_env_end(text, end, env)
            emit(text[i:stop], boundary=True)
            return stop
        if env in _MATH_ENVS:
            stop = _find_env_end(text, end, env)
            emit(_math(text[i:stop], ctx))
            return stop
        head_end = end
        m = _OVERLAY_RE.match(text, head_end)
        if m:
            head_end = m.end()
        spec = "O" if env in ctx.theorems else _ENV_ARGS.get(env, "U")
        args, stop = _take_args(text, head_end, spec)
        emit(_command_item(text[i:head_end], args, "block", ctx), boundary=True)
        return stop

    head_end = k
    if head_end < n and text[head_end] == "*":
        head_end += 1
    m = _OVERLAY_RE.match(text, head_end)
    if m and name in _RULES or (m and m.group(0)[1:2].isdigit()):
        head_end = m.end()
    head = text[i:head_end]

    if name in _RULES:
        spec, mode = _RULES[name]
        args, stop = _take_args(text, head_end, spec)
        item = _command_item(head, args, mode, ctx)
        emit(item, boundary=(mode == "block"))
        return stop

    if name.startswith(_PROTECTED_PREFIXES):
        args, stop = _unknown_args(text, head_end)
        emit(X([head] + [ws + g for _k, ws, g in args]))
        return stop

    args, stop = _unknown_args(text, head_end)
    args = [(("t" if _textlike(g[1:-1]) else "p") if g[0] == "{" else "o", ws, g) for _k, ws, g in args]
    emit(_command_item(head, args, "inline", ctx))
    return stop


def _unknown_args(text: str, pos: int) -> tuple[list[tuple[str, str, str]], int]:
    """Takes directly attached optional arguments and following brace groups of an unknown command."""
    args: list[tuple[str, str, str]] = []
    while pos < len(text) and text[pos] == "[":
        group, end = _read_group(text, pos, "[", "]")
        if group is None:
            break
        args.append(("o", "", group))
        pos = end
    while True:
        j = pos
        while j < len(text) and text[j] in " \t":
            j += 1
        if j < len(text) and text[j] == "{":
            group, end = _read_group(text, j, "{", "}")
            if group is None:
                break
            args.append(("p", text[pos:j], group))
            pos = end
        else:
            break
    return args, pos


def _inline(text: str, ctx: _Ctx) -> list:
    """Parses text that stays inside one sentence, paragraph breaks become kept markup."""
    out: list = []
    for item in _scan(text, ctx):
        if isinstance(item, _B):
            inner = item.item
            out.append(inner if isinstance(inner, X) else X([inner]))
        else:
            out.append(item)
    return out


def _is_edge(item) -> bool:
    return isinstance(item, X) or (isinstance(item, str) and not item.strip())


def _block(text: str, ctx: _Ctx) -> list:
    """Parses LaTeX into kept markup and translatable units, one per paragraph-like run."""
    out: list = []
    current: list = []

    def flush() -> None:
        lead: list = []
        trail: list = []
        while current and _is_edge(current[0]):
            lead.append(current.pop(0))
        while current and _is_edge(current[-1]):
            trail.insert(0, current.pop())
        if current and isinstance(current[0], str):
            s = current[0]
            lead.append(s[: len(s) - len(s.lstrip())])
            current[0] = s.lstrip()
        if current and isinstance(current[-1], str):
            s = current[-1]
            trail.insert(0, s[len(s.rstrip()):])
            current[-1] = s.rstrip()
        out.extend(lead)
        if current:
            out.append(Unit(list(current)))
        out.extend(trail)
        current.clear()

    for item in _scan(text, ctx):
        if isinstance(item, _B):
            flush()
            out.append(item.item)
        else:
            current.append(item)
    flush()
    return out


def _in_comment(text: str, idx: int) -> bool:
    line_start = text.rfind("\n", 0, idx) + 1
    return any(text[k] == "%" and not _is_escaped(text, k) for k in range(line_start, idx))


def _preamble(text: str, ctx: _Ctx) -> list:
    """Keeps the preamble and translates only titles, theorem names and caption names."""
    out: list = []
    pos = 0
    for m in _PREAMBLE_RE.finditer(text):
        if m.start() < pos or _is_escaped(text, m.start()) or _in_comment(text, m.start()):
            continue
        name = m.group(1)
        head_end = m.end() + (1 if text[m.end():m.end() + 1] == "*" else 0)
        if name == "newtheorem":
            args, stop = _take_args(text, head_end, "poto")
            if args and args[0][2].startswith("{"):
                ctx.theorems.add(args[0][2][1:-1].strip())
        elif name == "renewcommand":
            args, stop = _take_args(text, head_end, "pot")
            first = args[0][2].strip("{}").strip() if args else ""
            if first not in _CAPTION_NAMES:
                continue
        else:
            args, stop = _take_args(text, head_end, "t" if name == "date" else "Ot")
        out.append(text[pos:m.start()])
        out.append(_command_item(text[m.start():head_end], args, "block", ctx))
        pos = stop
    out.append(text[pos:])
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


def _split_document(text: str) -> tuple[str, str]:
    for m in re.finditer(r"\\begin\s*\{document\}", text):
        if not _in_comment(text, m.start()):
            return text[:m.start()], text[m.start():]
    return "", text


def translate_latex_preserve_structure(
    text: str, source_lang: str, target_lang: str, service: TranslationService
) -> str:
    if not text or not text.strip():
        return text

    text = fix_inputenc(text)
    text, german_shorthands = switch_language(text, target_lang)
    text = normalize_accents(text, german_shorthands)

    ctx = _Ctx()
    preamble, body = _split_document(text)
    template = _preamble(preamble, ctx) + _block(body, ctx)

    units = [u for u in _units(template) if _text_runs(u.parts)]
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
