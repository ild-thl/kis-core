"""Pure rules around the evaluation, without database access."""
import secrets

QUESTION_TYPES = ("choice", "multi", "text")

MAX_TITLE_CHARS = 120
MAX_INTRO_OUTRO_CHARS = 600
MAX_LINK_LABEL_CHARS = 80
MAX_LINK_URL_CHARS = 300
MAX_CONTACT_EMAIL_CHARS = 200
MAX_QUESTION_CHARS = 300
MAX_OPTION_CHARS = 120
MAX_OPTIONS = 12
MAX_QUESTIONS = 20

_JA_NEIN = ["Ja", "Eher ja", "Eher nein", "Nein"]
_HILFREICH = ["Sehr hilfreich", "Eher hilfreich", "Eher nicht hilfreich", "Nicht hilfreich"]
_LERNASSISTENT = "Lernassistent (Chat, Karteikarten, Quiz, ...)"
_INFOASSISTENT = "Infoassistent (allgemeine Fragen, Campus)"
_DIENSTE = "Dienste für Lehrende (Podcast, Präsentation, ...)"


def new_question_id() -> str:
    """Short id a question keeps for its whole life, stable across edits and answers."""
    return secrets.token_hex(4)


def default_config() -> dict:
    """A working first evaluation, so the admin edits something instead of starting blank.

    Fixed ids: nothing was saved yet, so this gets rebuilt on every read until the
    admin hits save. Random ids would then change on every read too, and a
    submission's answers would never match the questions it was shown for, and
    show_if below points at these same ids.
    """
    return {
        "active": False,
        "title": "Kurze Evaluation",
        "intro_text": "",
        "intro_link_label": "",
        "intro_link_url": "",
        "outro_text": "Vielen Dank, dass du dir die Zeit genommen hast.",
        "outro_link_label": "",
        "outro_link_url": "",
        # The repository fills in the installation's contact address while nothing was saved.
        "contact_email": "",
        "questions": [
            # Broad first (funnel technique), then the area question, then specific per area, open questions and the two overall verdicts last.
            {"id": "zurechtgefunden", "type": "choice", "text": "Hast du dich auf askFrancis zurechtgefunden?",
             "options": _JA_NEIN},
            {"id": "unklar", "type": "text", "text": "Was war unklar?",
             "show_if": {"question_id": "zurechtgefunden", "in": ["Eher nein", "Nein"]}},
            {"id": "intuitiv", "type": "choice", "text": "Fandest du askFrancis intuitiv zu bedienen?",
             "options": _JA_NEIN},

            {"id": "bereich", "type": "multi", "text": "Welchen Bereich von askFrancis hast du bisher genutzt?",
             "options": [_LERNASSISTENT, _INFOASSISTENT, _DIENSTE]},

            {"id": "la-hilfreich", "type": "choice", "text": "Wie hilfreich waren die Antworten vom Lernassistenten?",
             "options": _HILFREICH, "show_if": {"question_id": "bereich", "in": [_LERNASSISTENT]}},
            {"id": "la-quellen", "type": "choice", "text": "Wie gut konntest du nachvollziehen, woher eine Antwort stammt?",
             "options": ["Sehr gut", "Eher gut", "Eher schlecht", "Gar nicht"],
             "show_if": {"question_id": "bereich", "in": [_LERNASSISTENT]}},
            {"id": "la-tools", "type": "multi", "text": "Welche Tools im Lernassistenten fandest du gut?",
             "options": ["Karteikarten", "Quiz", "Datentabelle", "Mindmap"],
             "show_if": {"question_id": "bereich", "in": [_LERNASSISTENT]}},

            {"id": "ia-hilfreich", "type": "choice", "text": "Wie hilfreich waren die Antworten vom Infoassistenten?",
             "options": _HILFREICH, "show_if": {"question_id": "bereich", "in": [_INFOASSISTENT]}},

            {"id": "dienste-nuetzlich", "type": "multi", "text": "Welche der Dienste sind für dich nützlich?",
             "options": ["Übersetzung", "Text in Audio", "Transkript", "Zusammenfassung", "Podcast",
                         "Präsentation", "Screencast", "Bildgenerierung", "Glossar"],
             "show_if": {"question_id": "bereich", "in": [_DIENSTE]}},

            {"id": "gestoert", "type": "text", "text": "Was hat gestört, gefehlt oder nicht funktioniert?"},
            {"id": "nutzen", "type": "choice", "text": "Könntest du dir vorstellen, askFrancis regelmäßig zu nutzen?",
             "options": _JA_NEIN},
            {"id": "empfehlen", "type": "choice", "text": "Würdest du askFrancis weiterempfehlen?",
             "options": _JA_NEIN},
        ],
    }


def _validate_show_if(show_if: dict | None) -> dict | None:
    """A show_if names an earlier question and the answers that reveal this one."""
    if show_if is None:
        return None
    frage_id = (show_if.get("question_id") or "").strip()
    werte = [str(w).strip() for w in (show_if.get("in") or []) if str(w).strip()]
    if not frage_id or not werte:
        raise ValueError("show_if needs a question_id and at least one value")
    return {"question_id": frage_id, "in": werte}


def validate_questions(questions: list[dict]) -> list[dict]:
    """Trims and checks a question list, raises ValueError on anything unusable."""
    if not questions:
        raise ValueError("at least one question is required")
    if len(questions) > MAX_QUESTIONS:
        raise ValueError(f"at most {MAX_QUESTIONS} questions")
    bereinigt = []
    for frage in questions:
        typ = frage.get("type")
        if typ not in QUESTION_TYPES:
            raise ValueError(f"unknown question type {typ!r}")
        text = (frage.get("text") or "").strip()
        if not text:
            raise ValueError("question text must not be blank")
        if len(text) > MAX_QUESTION_CHARS:
            raise ValueError(f"question text must be at most {MAX_QUESTION_CHARS} characters")
        eintrag = {
            "id": frage.get("id") or new_question_id(),
            "type": typ,
            "text": text,
        }
        # Only choice and multi pick from a fixed list, a free text field has none.
        if typ in ("choice", "multi"):
            optionen = [(o or "").strip() for o in (frage.get("options") or []) if (o or "").strip()]
            if len(optionen) < 2:
                raise ValueError("choice and multi need at least two options")
            if len(optionen) > MAX_OPTIONS:
                raise ValueError(f"at most {MAX_OPTIONS} options")
            if any(len(o) > MAX_OPTION_CHARS for o in optionen):
                raise ValueError(f"an option must be at most {MAX_OPTION_CHARS} characters")
            eintrag["options"] = optionen
        show_if = _validate_show_if(frage.get("show_if"))
        if show_if:
            eintrag["show_if"] = show_if
        bereinigt.append(eintrag)
    return bereinigt


def _verteilung(werte: list, optionen: list[str], mehrfach: bool) -> dict[str, int]:
    """Counts how often each option was picked, zero included for options nobody chose.

    "not_tested" is the skip button's own value, never one of the admin's options,
    so it gets its own bucket and only shows up once someone actually used it.
    """
    zaehler = {option: 0 for option in optionen}
    zaehler["not_tested"] = 0
    for wert in werte:
        gewaehlt = wert if mehrfach and isinstance(wert, list) else [wert]
        for eintrag in gewaehlt:
            if eintrag in zaehler:
                zaehler[eintrag] += 1
    if zaehler["not_tested"] == 0:
        del zaehler["not_tested"]
    return zaehler


def summarize(responses: list[dict], questions: list[dict]) -> dict:
    """Turns raw submissions into the numbers the statistics tab shows.

    Submissions are only numbered, never tied back to an account: two answers
    from the same person read as two participants, which is the price of
    showing nothing that could identify anybody.
    """
    nach_frage: dict[str, list] = {frage["id"]: [] for frage in questions}
    for eintrag in responses:
        for antwort in eintrag["answers"]:
            if antwort["question_id"] in nach_frage:
                nach_frage[antwort["question_id"]].append(antwort["value"])

    fragen_auswertung = []
    for frage in questions:
        werte = nach_frage[frage["id"]]
        if frage["type"] in ("choice", "multi"):
            mehrfach = frage["type"] == "multi"
            beantwortet = [w for w in werte if w]
            fragen_auswertung.append({
                "id": frage["id"],
                "type": frage["type"],
                "text": frage["text"],
                "answered": len(beantwortet),
                "distribution": _verteilung(beantwortet, frage["options"], mehrfach),
            })
        else:
            texte = [str(w).strip() for w in werte if str(w).strip()]
            fragen_auswertung.append({
                "id": frage["id"],
                "type": "text",
                "text": frage["text"],
                "answered": len(texte),
                "answers": texte,
            })

    # Oldest first, so participant 1 is the first person who answered.
    sortiert = sorted(responses, key=lambda e: e["created_at"])
    teilnahmen = [
        {
            "number": nummer,
            "created_at": eintrag["created_at"],
            "answers": eintrag["answers"],
        }
        for nummer, eintrag in enumerate(sortiert, start=1)
    ]

    return {"total": len(responses), "questions": fragen_auswertung, "responses": teilnahmen}


def validate_answers(answers: list[dict], questions: list[dict]) -> list[dict]:
    """Keeps only answers to questions that still exist, in the evaluation's own order."""
    nach_id = {antwort.get("question_id"): antwort.get("value") for antwort in answers}
    bereinigt = []
    for frage in questions:
        wert = nach_id.get(frage["id"])
        if wert is None:
            continue
        if isinstance(wert, str) and not wert.strip():
            continue
        if isinstance(wert, list) and not wert:
            continue
        bereinigt.append({"question_id": frage["id"], "value": wert})
    if not bereinigt:
        raise ValueError("at least one answer is required")
    return bereinigt
