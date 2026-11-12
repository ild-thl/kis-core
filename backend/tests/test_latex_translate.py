"""LaTeX translation keeps the document compilable with DeepL, an LLM or any other client."""
import html
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from src.services.deepl_client import DeepLClient
from src.services.glossary import GlossaryService
from src.services.llm_translation_client import LLMTranslationClient
from src.services.translation import TranslationService
from src.translators.latex import translate_latex_preserve_structure
from src.translators.latex_source import decode_tex
from src.translators.latex_tags import TAG_RE, _map_text, tags_match


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
        r"\begin{tabular}{|l|c|}", r"node[above] {Punkt};", r"\vspace{1cm}", r"\texttt{print()}",
        r'\verb|"a{|', 'x = "Hallo"', "% Kommentar", r"\label{sec:a}", r"SIEHE~\ref{sec:a}",
        r"\textcolor{red}{ACHTUNG}",
    ):
        assert kept in out, kept


def test_text_titles_and_nested_pieces_are_translated():
    out, _ = _run(DOC)
    for translated in (
        r"\title{EINFÜHRUNG}", r"\newtheorem{satz}{SATZ}[section]", r"\section{EINLEITUNG}",
        r"\textbf{WICHTIGER}", r"\footnote{EINE FUSSNOTE.}", r"\begin{satz}[SATZ VON PYTHAGORAS]",
        r"\text{FÜR ALLE SEITEN}", r"\caption{EIN BILD}", r"NAME & WERT \\ \hline",
    ):
        assert translated in out, translated


def test_whole_sentence_goes_out_with_tags():
    _out, client = _run(DOC)
    sentence = next(t for t in client.texts if t.startswith("Dies ist"))
    assert sentence == "Dies ist ein <g1>wichtiger</g1> Satz mit <x2/>, siehe<x3/><x4/>. Zweiter Satz<x5/> hier."
    assert not client.pieces


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
    assert "ÄRGER \\glqq{}GROSS\\grqq{} UND MÄDCHEN." in out
    assert any("Ärger" in t and "Mädchen" in t for t in client.texts)


class _Specials(_Upper):
    def translate_text(self, text, source_lang, target_lang):
        self.texts.append(text)
        return "R&D 100% #1 a_b $5 {x} ~"


def test_special_characters_in_the_translation_are_escaped():
    out, _ = _run("Forschung und Entwicklung", client=_Specials())
    assert out == r"R\&D 100\% \#1 a\_b \$5 \{x\} \textasciitilde{}"


def test_escaped_source_characters_reach_the_translator_as_plain_text():
    out, client = _run(r"Gewinn 50\,\% \& mehr")
    assert client.texts == ["Gewinn 50<x1/>% & mehr"]
    assert out == r"GEWINN 50\,\% \& MEHR"


class _FakeDeepL:
    def __init__(self):
        self.kwargs: dict = {}

    def translate_text(self, texts, **kwargs):
        self.kwargs = kwargs
        return [
            SimpleNamespace(text=_map_text(t, lambda s: html.escape(html.unescape(s).upper(), quote=False)))
            for t in texts
        ]


def test_deepl_gets_xml_tags_and_escaped_text():
    client = DeepLClient.__new__(DeepLClient)
    fake = _FakeDeepL()
    client._translator = fake
    out, _ = _run(r"Ein \textbf{fetter} Text mit a < b \& c.", client=client)
    assert fake.kwargs["tag_handling"] == "xml"
    assert out == r"EIN \textbf{FETTER} TEXT MIT A < B \& C."


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


def test_quote_tags_written_as_pairs_are_repaired():
    client = _llm(lambda user: "Girls are <x1>great<x2/>.")
    out, _ = _run("M\\\"adchen sind \\glqq{}toll\\grqq{}.", client=client)
    assert out == r"Girls are \glqq{}great\grqq{}."


def test_glossary_applies_inside_tagged_paragraphs():
    glossary = GlossaryService()
    glossary.set_entries({"Hochschule": "University"})
    out, client = _run(r"Die \emph{Hochschule} ist gross.", glossary=glossary)
    assert "__GLOSSARY_0__" in client.texts[0]
    assert r"\emph{University}" in out


def test_tags_match_rules():
    assert tags_match("a <g1>b</g1> <x2/>", "<x2/> A <g1>B</g1>")
    assert not tags_match("a <g1>b</g1> <x2/>", "A <g1>B</g1>")
    assert not tags_match("a <g1><g2>b</g2></g1>", "A <g1><g2>B</g1></g2>")
    assert not tags_match("a <x1/>", "<x1/>")


def test_decode_tex_handles_old_encodings():
    assert decode_tex("Grüße".encode("utf-8")) == "Grüße"
    assert decode_tex("Grüße".encode("cp1252")) == "Grüße"
    mac = b"\\usepackage[applemac]{inputenc}\n" + "Grüße".encode("mac_roman")
    assert decode_tex(mac).endswith("Grüße")
    with pytest.raises(ValueError):
        decode_tex(b"\x00\x01binary")


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
