"""Language independent sentence splitting, precision before completeness."""
from src.features.ai_assistant.routes._text import _split_sentences


# ── the happy path: real boundaries split ────────────────────────────────────

def test_splits_two_plain_sentences():
    assert _split_sentences("Der Kurs startet im April. Die Abgabe ist im Juli.") == [
        "Der Kurs startet im April.",
        "Die Abgabe ist im Juli.",
    ]


def test_splits_on_question_and_exclamation():
    assert _split_sentences("Was ist Wissenschaft? Das klaert der Kurs!") == [
        "Was ist Wissenschaft?",
        "Das klaert der Kurs!",
    ]


def test_single_sentence_returns_one_unit():
    assert _split_sentences("Nur ein Satz ohne weiteren Punkt dahinter.") == [
        "Nur ein Satz ohne weiteren Punkt dahinter."
    ]


def test_english_sentences_split():
    assert _split_sentences("The deadline is July 3rd. Submit on time.") == [
        "The deadline is July 3rd.",
        "Submit on time.",
    ]


# ── guards: these must NOT split (would put a chip mid-sentence) ──────────────

def test_no_split_on_single_letter_abbreviation_zb():
    # "z. B." (spaced) must stay inside the sentence.
    assert _split_sentences("Nutze Tools wie z. B. Zotero. Das hilft dabei.") == [
        "Nutze Tools wie z. B. Zotero.",
        "Das hilft dabei.",
    ]


def test_no_split_on_page_ref_S():
    # A page reference stays intact, a missed cut is harmless.
    assert _split_sentences("Die Quelle steht auf S. 5 im Anhang. Der Termin folgt.") == [
        "Die Quelle steht auf S. 5 im Anhang.",
        "Der Termin folgt.",
    ]


def test_no_split_on_decimal_number():
    assert _split_sentences("Der Wert liegt bei 6.2 Prozent im Schnitt. Das ist viel.") == [
        "Der Wert liegt bei 6.2 Prozent im Schnitt.",
        "Das ist viel.",
    ]


def test_no_split_on_german_ordinal_date():
    # "am 3. Juli" is one sentence — the digit-before-period guard keeps it together.
    assert _split_sentences("Die Abgabe ist am 3. Juli faellig. Bitte einhalten.") == [
        "Die Abgabe ist am 3. Juli faellig.",
        "Bitte einhalten.",
    ]


def test_no_split_on_capitalized_short_abbreviation():
    # "Prof." / "Dr." are capitalized tokens of length <= 4 -> treated as abbreviations.
    assert _split_sentences("Betreut von Prof. Meyer im Seminar. Kontakt per Mail.") == [
        "Betreut von Prof. Meyer im Seminar.",
        "Kontakt per Mail.",
    ]


def test_no_split_on_hyphenated_academic_title():
    # "Dr.-Ing." is one abbreviation, not two short tokens -> must not split before the name.
    assert _split_sentences("Betreut von Prof. Dr.-Ing. Malte Kaltenbach im Seminar. Kontakt per Mail.") == [
        "Betreut von Prof. Dr.-Ing. Malte Kaltenbach im Seminar.",
        "Kontakt per Mail.",
    ]


def test_no_split_inside_chained_lowercase_title():
    # "Dr. rer. pol." chains short lowercase pieces, the name behind it stays in the sentence.
    assert _split_sentences("Der Professor heißt Dr. rer. pol. Jürgen Klein. Er betreut das Modul.") == [
        "Der Professor heißt Dr. rer. pol. Jürgen Klein.",
        "Er betreut das Modul.",
    ]


def test_split_after_lone_short_lowercase_word():
    # A short lowercase word without a period before it still ends a sentence.
    assert _split_sentences("Das Ziel ist neu. Danach folgt mehr.") == [
        "Das Ziel ist neu.",
        "Danach folgt mehr.",
    ]


def test_no_split_inside_email():
    assert _split_sentences("Schreib an lenka.kleinau@example.org. Sie antwortet schnell.") == [
        "Schreib an lenka.kleinau@example.org.",
        "Sie antwortet schnell.",
    ]


def test_no_split_on_parenthesized_abbreviation():
    # An opening bracket must not hide the abbreviation behind it.
    assert _split_sentences("Nutze Datenbanken (z. B. DBIS und ACM) im Katalog. Das hilft dabei.") == [
        "Nutze Datenbanken (z. B. DBIS und ACM) im Katalog.",
        "Das hilft dabei.",
    ]


def test_no_split_on_dotted_abbreviation_ua():
    # "u.a." (no spaces) contains an internal period -> abbreviation, no split before "Zotero".
    assert _split_sentences("Genutzt werden u.a. Zotero und Citavi. Beide sind gut.") == [
        "Genutzt werden u.a. Zotero und Citavi.",
        "Beide sind gut.",
    ]


# ── shape / robustness ───────────────────────────────────────────────────────

def test_no_boundary_returns_text_unchanged():
    assert _split_sentences("Ein Fragment ohne Satzende") == ["Ein Fragment ohne Satzende"]


def test_empty_string_returns_empty_list():
    assert _split_sentences("   ") == []


def test_join_reconstructs_prose_with_single_spaces():
    text = "Erster Satz hier. Zweiter Satz dort. Dritter Satz da."
    assert " ".join(_split_sentences(text)) == text
