"""LaTeX translation keeps the document compilable with DeepL, an LLM or any other client."""
import html
import re
import time
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from src.services.deepl_client import DeepLClient
from src.services.glossary import GlossaryService
from src.services.llm_translation_client import LLMTranslationClient
from src.services.translation import TranslationService
from src.translators.latex import translatable_text, translate_latex_preserve_structure
from src.translators.latex_source import decode_tex, read_tex, write_tex
from src.translators.latex_tags import TAG_RE, _map_text, repair_tags, tags_match


class _Upper:
    """A client of unknown type that upper-cases text and keeps tags."""

    def __init__(self):
        self.texts: list[str] = []
        self.pieces: list[str] = []

    def translate_text(self, text, source_lang, target_lang):
        self.texts.append(text)
        return _map_text(text, str.upper)

    def translate_batch(self, texts, source_lang, target_lang):
        self.pieces.extend(texts)
        return [t.upper() for t in texts]


def _run(doc: str, client=None, target: str = "EN-US", glossary=None) -> tuple[str, object]:
    client = client or _Upper()
    service = TranslationService(deepl_client=client, glossary=glossary or GlossaryService())
    return translate_latex_preserve_structure(doc, "DE", target, service), client


DOC = r"""\documentclass[a4paper]{scrartcl}
\usepackage[latin1]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[ngerman]{babel}
\usepackage{geometry,xcolor,tikz,listings,hyperref,amsmath,amsthm}
\geometry{a4paper, margin=2cm}
\newcommand{\R}{\mathbb{R}}
\definecolor{hell}{RGB}{0,80,160}
\newtheorem{satz}{Satz}[section]
\title{Einf\"uhrung}
\author{Max Muster}
\begin{document}
\maketitle
\section{Einleitung}\label{sec:a}
Dies ist ein \textbf{wichtiger} Satz mit $x^2$, siehe~\ref{sec:a}.
Zweiter Satz\footnote{Eine Fu"snote.} hier. % Kommentar

\begin{satz}[Satz von Pythagoras]
Es gilt \[ a^2+b^2=c^2 \quad \text{f\"ur alle Seiten} \]
\end{satz}
\begin{figure}[htbp]
\centering
\caption{Ein Bild}
\end{figure}
\begin{tabular}{|l|c|}
Name & Wert \\ \hline
\end{tabular}
\begin{tikzpicture}
\draw (0,0) -- (1,1) node[above] {Punkt};
\end{tikzpicture}
\vspace{1cm}
\textcolor{red}{Achtung} und \texttt{print()} und \verb|"a{|.
\begin{lstlisting}
x = "Hallo"
\end{lstlisting}
\end{document}
"""


def test_markup_and_preamble_stay_as_written():
    out, _ = _run(DOC)
    for kept in (
        r"\geometry{a4paper, margin=2cm}", r"\newcommand{\R}{\mathbb{R}}",
        r"\definecolor{hell}{RGB}{0,80,160}", r"\author{Max Muster}", r"\begin{figure}[htbp]",
        r"\begin{tabular}{|l|c|}", r"\draw (0,0) -- (1,1) node[above]", r"\vspace{1cm}", r"\texttt{print()}",
        r'\verb|"a{|', 'x = "Hallo"', "% Kommentar", r"\label{sec:a}", r"SIEHE~\ref{sec:a}",
        r"\textcolor{red}{ACHTUNG}",
    ):
        assert kept in out, kept


def test_text_titles_and_nested_pieces_are_translated():
    out, _ = _run(DOC)
    for translated in (
        r"\title{EINFÜHRUNG}", r"\newtheorem{satz}{SATZ}[section]", r"\section{EINLEITUNG}",
        r"\textbf{WICHTIGER}", r"\footnote{EINE FUSSNOTE.}", r"\begin{satz}[SATZ VON PYTHAGORAS]",
        r"\text{FÜR ALLE SEITEN}", r"\caption{EIN BILD}", r"NAME & WERT \\ \hline", r"node[above] {PUNKT};",
    ):
        assert translated in out, translated


def test_whole_sentence_goes_out_with_tags():
    _out, client = _run(DOC)
    sentence = next(t for t in client.texts if t.startswith("Dies ist"))
    assert sentence == "Dies ist ein <g1>wichtiger</g1> Satz mit <x2/>, siehe\u00a0<x3/>. Zweiter Satz<x4/> hier."
    assert not client.pieces


SPECIAL = r"""\newcommand{\kursname}{Werkstoffkunde}
\newcommand{\farbe}{blue}
\newcommand{\R}{\mathbb{R}}
\begin{document}
\begin{lstlisting}[caption={Sortieren durch Einf\"ugen}, language=Python]
x = "Hallo"  # Kommentar
\end{lstlisting}
\begin{tikzpicture}
\node[draw] (a) at (0,0) {Eingabe};
\begin{axis}[xlabel={Zeit in s}, node distance=2cm]
\end{axis}
\end{tikzpicture}
\begin{algorithmic}
\For{$i \gets 2$ \textbf{bis} $n$}
  \State $s \gets A[i]$ \Comment{aktuelles Element}
\EndFor
\end{algorithmic}
Es gilt
\[ a = b \]
wobei $a$ klein ist.
\begin{thebibliography}{9}
\bibitem{k} D. Knuth: \emph{Die Kunst des Programmierens}.
\end{thebibliography}
\end{document}"""


def test_labels_captions_pseudocode_and_text_macros_are_translated():
    out, _ = _run(SPECIAL)
    for expected in (
        r"\newcommand{\kursname}{WERKSTOFFKUNDE}", r"\newcommand{\farbe}{blue}", r"\newcommand{\R}{\mathbb{R}}",
        r"caption={SORTIEREN DURCH EINFÜGEN}, language=Python]", 'x = "Hallo"  # Kommentar',
        r"(a) at (0,0) {EINGABE};", r"xlabel={ZEIT IN S}, node distance=2cm]",
        r"\For{$i \gets 2$ \textbf{BIS} $n$}", r"\State $s \gets A[i]$ \Comment{AKTUELLES ELEMENT}", r"\EndFor",
        r"\emph{Die Kunst des Programmierens}",
    ):
        assert expected in out, expected


def test_displayed_formula_keeps_its_own_lines():
    out, _ = _run(SPECIAL)
    assert "ES GILT\n\\[ a = b \\]\nWOBEI $a$ KLEIN IST." in out


def test_space_next_to_kept_pieces_is_restored():
    client = _llm(lambda user: "Wir fügen<x1/>hinzu.<x2/>Die Wahl.")
    out, _ = _run(r"We add $x$ here.\footnote{Note.} The choice.", client=client, target="DE")
    assert out.startswith(r"Wir fügen $x$ hinzu.\footnote{") and out.endswith("} Die Wahl.")


def test_straight_quotes_from_the_translator_become_typographic():
    client = _llm(lambda user: 'He said "hello" <x1/>.')
    out, _ = _run(r"Er sagte hallo $x$.", client=client, target="EN-US")
    assert out == "He said “hello” $x$."
    out, _ = _run(r"He said hello $x$.", client=client, target="DE")
    assert out == "He said „hello“ $x$."


def test_paragraph_breaks_survive():
    out, _ = _run(DOC)
    assert "% Kommentar\n\n\\begin{satz}" in out


def test_preamble_switches_to_utf8_and_target_language():
    out, _ = _run(DOC)
    assert r"\usepackage[utf8]{inputenc}" in out
    assert r"\usepackage[english]{babel}" in out
    out_fr, _ = _run(DOC, target="FR")
    assert r"\usepackage[french]{babel}" in out_fr


def test_babel_language_in_class_options_and_polyglossia():
    out, _ = _run("\\documentclass[11pt,ngerman]{article}\n\\usepackage{babel}\n\\begin{document}\nHallo\n\\end{document}")
    assert r"\documentclass[11pt,english]{article}" in out
    out, _ = _run("\\usepackage{polyglossia}\n\\setdefaultlanguage[spelling=new]{german}\n\\begin{document}\nHallo\n\\end{document}")
    assert r"\setdefaultlanguage{english}" in out


def test_accents_and_german_shorthands_become_letters():
    out, client = _run('\\usepackage[ngerman]{babel}\n\\begin{document}\n"Arger "`gro"s"\' und M\\"adchen.\n\\end{document}')
    assert "ÄRGER „GROSS“ UND MÄDCHEN." in out
    assert any("Ärger" in t and "Mädchen" in t for t in client.texts)


class _Echo(_Upper):
    """Returns the text unchanged, to look at what the pipeline itself does."""

    def translate_text(self, text, source_lang, target_lang):
        self.texts.append(text)
        return text


class _Specials(_Upper):
    def translate_text(self, text, source_lang, target_lang):
        self.texts.append(text)
        return "R&D 100% #1 a_b $5 {x} ~"


def test_special_characters_in_the_translation_are_escaped():
    out, _ = _run("Forschung und Entwicklung", client=_Specials())
    assert out == r"R\&D 100\% \#1 a\_b \$5 \{x\} \textasciitilde{}"


def test_escaped_source_characters_reach_the_translator_as_plain_text():
    out, client = _run(r"Gewinn 50\,\% \& mehr")
    assert client.texts == ["Gewinn 50\u202f% & mehr"]
    assert out == r"GEWINN 50\,\% \& MEHR"


class _FakeDeepL:
    def __init__(self):
        self.kwargs: dict = {}
        self.sent: list[str] = []

    def translate_text(self, texts, **kwargs):
        self.kwargs = kwargs
        self.sent.extend(texts)

        def upper(text):
            parts = re.split(r'(<x i="\d+">.*?</x>|<[^>]+>)', text)
            return "".join(p if p.startswith("<") else html.escape(html.unescape(p).upper(), quote=False) for p in parts)

        return [SimpleNamespace(text=upper(t)) for t in texts]


def test_deepl_gets_formula_sources_as_ignored_content_and_context():
    client = DeepLClient.__new__(DeepLClient)
    fake = _FakeDeepL()
    client._translator = fake
    out, _ = _run("\\section{Folgen}\nEin \\textbf{fetter} Text mit $a<b$ und a < b \\& c.", client=client)
    assert fake.kwargs["tag_handling"] == "xml" and fake.kwargs["ignore_tags"] == ["x"]
    assert '<x i="2">$a&lt;b$</x>' in fake.sent[1]
    assert "Folgen" in fake.kwargs["context"] and "fetter Text" in fake.kwargs["context"]
    assert out == "\\section{FOLGEN}\nEIN \\textbf{FETTER} TEXT MIT $a<b$ UND A < B \\& C."


def _llm(answer):
    client = LLMTranslationClient(api_key="k", base_url="http://x/v1", model="m", provider="test")
    client.calls = []

    def completion(system, user, max_tokens=None, item_count=1):
        client.calls.append((system, user))
        return answer(user), "stop"

    client._completion_with_retry = completion
    return client


def test_llm_batch_prompt_explains_tags():
    client = _llm(lambda user: user.upper().replace("<G", "<g").replace("</G", "</g").replace("<X", "<x"))
    out, _ = _run("Erster \\textbf{Absatz}.\n\nZweiter Absatz $x$.", client=client)
    assert "<g1>...</g1>" in client.calls[0][0]
    assert len(client.calls) == 1
    assert out == "ERSTER \\textbf{ABSATZ}.\n\nZWEITER ABSATZ $x$."


def test_lost_tags_fall_back_to_piece_by_piece():
    client = _llm(lambda user: TAG_RE.sub("", user).upper())
    client.translate_batch = lambda texts, s, t: [x.upper() for x in texts]
    out, _ = _run(r"Ein \textbf{fetter} Text mit $x$.", client=client)
    assert out == r"EIN \textbf{FETTER} TEXT MIT $x$."


def test_tags_written_as_pairs_are_repaired():
    client = _llm(lambda user: "See <x1>and<x2/>.")
    out, _ = _run(r"Siehe \ref{a} und \ref{b}.", client=client)
    assert out == r"See \ref{a} and \ref{b}."


def test_german_quote_commands_become_quote_characters():
    out, client = _run(r"Eine \glqq Nullfolge\grqq{} hier.")
    assert client.texts == ["Eine „Nullfolge“ hier."]
    assert out == "EINE „NULLFOLGE“ HIER."


def test_glossary_applies_inside_tagged_paragraphs():
    glossary = GlossaryService()
    glossary.set_entries({"Hochschule": "University"})
    out, client = _run(r"Die \emph{Hochschule} ist gross.", glossary=glossary)
    assert "__GLOSSARY_0__" in client.texts[0]
    assert r"\emph{University}" in out


def test_repeated_tag_pairs_keep_only_the_first():
    assert repair_tags("A <g1>material</g1> is a <g1>substance</g1>.") == "A <g1>material</g1> is a substance."
    assert repair_tags("<x1/> and <x1/> <x2>") == "<x1/> and  <x2/>"
    assert tags_match("Ein <g1>Werkstoff</g1> ist", repair_tags("A <g1>a</g1> b <g1>c</g1>"))


def test_tags_match_rules():
    assert tags_match("a <g1>b</g1> <x2/>", "<x2/> A <g1>B</g1>")
    assert not tags_match("a <g1>b</g1> <x2/>", "A <g1>B</g1>")
    assert not tags_match("a <g1><g2>b</g2></g1>", "A <g1><g2>B</g1></g2>")
    assert not tags_match("a <x1/>", "<x1/>")


def _roundtrip(raw: bytes, target: str = "EN-US", client=None) -> bytes:
    source = read_tex(raw)
    service = TranslationService(deepl_client=client or _Upper(), glossary=GlossaryService())
    out = translate_latex_preserve_structure(source.text, "DE", target, service, utf8_output=source.utf8_output)
    return write_tex(out, source)


def test_latin1_result_keeps_its_encoding_and_writes_missing_characters_as_commands():
    source = read_tex("Größe".encode("cp1252"))
    assert source.codec == "latin-1"
    assert write_tex("Größe “outlier” — Gauss’s ő…", source).decode("latin-1") == "Größe ``outlier'' --- Gauss's \\H{o}\\ldots{}"


def test_windows_1252_extras_are_kept_when_the_upload_used_them():
    source = read_tex("„Zitat“".encode("cp1252"))
    assert write_tex("“Quote”", source).decode("cp1252") == "“Quote”"


def test_utf8_result_stays_utf8():
    assert write_tex("“Quote” — ő", read_tex("Grüße".encode("utf-8"))) == "“Quote” — ő".encode("utf-8")


def test_latin1_document_keeps_its_inputenc():
    doc = "\\usepackage[latin1]{inputenc}\n\\begin{document}\nGrüße\n\\end{document}"
    out = _roundtrip(doc.encode("cp1252")).decode("latin-1")
    assert "\\usepackage[latin1]{inputenc}" in out and "GRÜSSE" in out


def test_ascii_chapter_stays_ascii_so_it_fits_any_main_file():
    out = _roundtrip(b'\\section{"Ubung}\nDie W"arme flie"st, die Gr\\"o\\ss e z"ahlt.\n', client=_Echo())
    assert out.isascii()
    assert out.decode() == '\\section{\\"Ubung}\nDie W\\"arme flie\\ss{}t, die Gr\\"o\\ss{}e z\\"ahlt.\n'


def test_modern_ascii_document_may_get_utf8_umlauts():
    client = _llm(lambda user: "Grüße")
    out = _roundtrip(b"\\documentclass{article}\n\\begin{document}\nGreetings\n\\end{document}\n", target="DE", client=client)
    assert "Grüße".encode("utf-8") in out


def test_target_script_outside_the_encoding_switches_the_file_to_utf8():
    client = _llm(lambda user: "Привет")
    doc = "\\usepackage[latin1]{inputenc}\n\\begin{document}\nGrüße\n\\end{document}"
    out = _roundtrip(doc.encode("cp1252"), target="RU", client=client).decode("utf-8")
    assert "\\usepackage[utf8]{inputenc}" in out and "Привет" in out


def test_windows_line_endings_keep_paragraphs_apart():
    out = _roundtrip("Erster Absatz.\r\n\r\nZweiter Absatz.\r\n".encode("cp1252"))
    assert out == b"ERSTER ABSATZ.\r\n\r\nZWEITER ABSATZ.\r\n"


def test_old_german_package_turns_shorthands_on_and_becomes_babel():
    doc = '\\documentclass{article}\n\\usepackage{german,epsfig}\n\\begin{document}\nDie "Anderung "`hier"\'.\n\\end{document}\n'
    out, client = _run(doc)
    assert "\\usepackage{epsfig}\\usepackage[english]{babel}" in out
    assert client.texts == ["Die Änderung „hier“."]


def test_index_entries_with_syntax_are_kept():
    out, _ = _run(r"Text\index{Norm!alte}\index{Wort} hier.")
    assert r"\index{Norm!alte}" in out and r"\index{WORT}" in out


def test_decode_tex_handles_old_encodings():
    assert decode_tex("Grüße".encode("utf-8")) == "Grüße"
    assert decode_tex("Grüße".encode("cp1252")) == "Grüße"
    mac = b"\\usepackage[applemac]{inputenc}\n" + "Grüße".encode("mac_roman")
    assert decode_tex(mac).endswith("Grüße")
    with pytest.raises(ValueError):
        decode_tex(b"\x00\x01binary")


def test_length_count_is_what_the_translator_gets():
    counted = translatable_text(
        "\\title{Langer Titel}\\geometry{margin=2cm}\n\\begin{document}\nEs gilt $x \\text{für alle Seiten}$.\n\\end{document}"
    )
    assert "Langer Titel" in counted and "für alle Seiten" in counted
    assert "margin" not in counted


@pytest.mark.parametrize("doc", [
    "{" * 300_000, "{\n\nWort " * 50_000, "\\foo[" * 60_000, "\\begin{verbatim}" * 20_000,
    "\\usepackage[" * 25_000, "$" + "\\text{" * 50_000 + "$", "\\textbf{" * 5_000 + "a" + "}" * 5_000,
    "\\foo{" + "1" * 300_000 + "x}", "\\title{a}" * 30_000 + "\\begin{document}x",
    "\\renewcommand{" * 60_000 + "x" + "}" * 60_000 + "\\begin{document}x",
    "\\newtheorem{" * 60_000 + "x" + "}" * 60_000 + "\\begin{document}x",
])
def test_hostile_input_is_parsed_in_linear_time(doc):
    start = time.monotonic()
    translatable_text(doc)
    assert time.monotonic() - start < 3


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_translated_document_compiles(tmp_path):
    out, _ = _run(DOC.replace(r"\begin{tikzpicture}", "").replace(r"\draw (0,0) -- (1,1) node[above] {Punkt};", "")
                  .replace(r"\end{tikzpicture}", ""))
    (tmp_path / "doc.tex").write_text(out, encoding="utf-8")
    result = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "doc.tex"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout[-2000:]
