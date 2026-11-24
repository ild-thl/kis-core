"""Writing phase: plan the outline over the material, write section by section, assemble."""

import asyncio
import copy
import json
import re

from loguru import logger

from src.features.summary.models import GROUND_RULES, Caller, Outline, Section
from src.services import anweisung
from src.services.upstream_errors import is_provider_refusal
from src.limits import (
    SUMMARY_CHARS_PER_SECTION,
    SUMMARY_COMPOSE_MAX_ATTEMPTS,
    SUMMARY_JSON_REPAIR_LINES,
    SUMMARY_MAX_SECTIONS,
    SUMMARY_MIN_SECTIONS,
    SUMMARY_OUTLINE_MAX_ATTEMPTS,
    SUMMARY_OUTLINE_MAX_TOKENS,
    SUMMARY_PROMPT_RESERVE_CHARS,
    SUMMARY_RETRY_DELAY_SECONDS,
    SUMMARY_SECTION_BASE_CHARS,
    SUMMARY_SECTION_GROUP_CHARS,
    SUMMARY_SECTIONS_PER_SOURCE,
    SUMMARY_WRITE_MAX_TOKENS,
)

OUTLINE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "outline",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": (
                        "The title of the finished document, in the output language: a short "
                        "noun phrase naming what the material is about. No file name, no "
                        "word for the format such as summary or briefing."
                    ),
                },
                "intro": {
                    "type": "string",
                    "description": (
                        "The opening summary in the output language. The first sentence says "
                        "what the material covers, the rest gives its most important "
                        "statements with their figures. Never a restatement of these "
                        "instructions."
                    ),
                },
                "documents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string"},
                            "short_name": {
                                "type": "string",
                                "description": (
                                    "The short name the document's own text uses for itself, "
                                    "such as a law's abbreviation, else a title of two to four "
                                    "words. Never the file name."
                                ),
                            },
                        },
                        "required": ["file", "short_name"],
                        "additionalProperties": False,
                    },
                },
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "section_index": {"type": "integer"},
                            "title": {"type": "string",
                                      "description": "A short noun phrase, no numbering."},
                            "description": {
                                "type": "string",
                                "description": "One sentence on what belongs in it and what does not.",
                            },
                            "refs": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "The labels from the material this section rests on, "
                                    'copied exactly, each such as "SZ12" or a range such as '
                                    '"SZ12-SZ15", topics as "TZ3".'
                                ),
                            },
                            "start": {
                                "type": "string",
                                "description": (
                                    "The first six to ten words of the text this section rests "
                                    "on, copied exactly from the material, never a label. Empty "
                                    "when the material is a list of topics."
                                ),
                            },
                        },
                        "required": ["section_index", "title", "description", "refs", "start"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["title", "intro", "documents", "sections"],
            "additionalProperties": False,
        },
    },
}


def outline_schema(extra: dict | None = None) -> dict:
    """The planning schema, widened by a tool's own fields that come out of the same call."""
    if not extra:
        return OUTLINE_SCHEMA
    schema = copy.deepcopy(OUTLINE_SCHEMA)
    inner = schema["json_schema"]["schema"]
    inner["properties"].update(extra)
    inner["required"] = inner["required"] + list(extra)
    return schema


def _example(feld: dict):
    """An empty value of a schema field, the shape a model fills in."""
    if "enum" in feld:
        return feld["enum"][0]
    art = feld.get("type")
    if art == "array":
        return [_example(feld.get("items") or {"type": "string"})]
    if art == "object":
        return {k: _example(v) for k, v in (feld.get("properties") or {}).items()}
    return 0 if art == "integer" else ""


def _descriptions(eigenschaften: dict, vorne: str = "") -> list[str]:
    zeilen = []
    for k, v in eigenschaften.items():
        if v.get("description"):
            zeilen.append(f"- {vorne}{k}: {v['description']}")
        unten = (v.get("items") or {}).get("properties") if v.get("type") == "array" else v.get("properties")
        if unten:
            zeilen += _descriptions(unten, f"{vorne}{k}.")
    return zeilen


def outline_shape(extra: dict | None = None) -> str:
    """The plan's shape in words, for a call that leaves the schema unenforced."""
    eigenschaften = {**OUTLINE_SCHEMA["json_schema"]["schema"]["properties"], **(extra or {})}
    return ("Answer with one JSON object and nothing else, no code fence, in this shape:\n"
            + json.dumps({k: _example(v) for k, v in eigenschaften.items()}, ensure_ascii=False)
            + "\nWhat the fields hold:\n" + "\n".join(_descriptions(eigenschaften)))


def target_sections(material_chars: int, sources: int = 1,
                    span: tuple[int, int] | None = None) -> int:
    """How many sections the material carries, a target the planner may deviate from.

    Never fewer than every source needs: with unrelated files a count drawn from the
    size alone leaves the last of them without a heading to stand under. A template with
    its own span keeps to it, however much material there is.
    """
    lo, hi = span or (SUMMARY_MIN_SECTIONS, SUMMARY_MAX_SECTIONS)
    aus_umfang = material_chars // SUMMARY_CHARS_PER_SECTION
    aus_quellen = SUMMARY_SECTIONS_PER_SOURCE * max(1, sources)
    return max(lo, min(hi, max(aus_umfang, aus_quellen)))


def cut_to_last_line(text: str) -> str:
    """Drops a line the cap cut in half, unless that would drop most of the text."""
    schnitt = text.rfind("\n")
    return text[:schnitt].rstrip() if schnitt > len(text) // 2 else text


def _strip_thinking(raw: str | None) -> str:
    """Drops a leading thinking block and a fenced wrapper some models add."""
    antwort = (raw or "").strip()
    if antwort.startswith("<think>"):
        ende = antwort.find("</think>")
        if ende != -1:
            antwort = antwort[ende + len("</think>"):].strip()
    if antwort.startswith("```"):
        ohne_zaun = antwort.split("\n", 1)
        if len(ohne_zaun) == 2:
            antwort = ohne_zaun[1].rsplit("```", 1)[0].strip()
    return antwort


def loose_json(text: str):
    """The first JSON object in a text, a line the model garbled is dropped. None when unreadable."""
    treffer = re.search(r"\{.*\}", text, re.S)
    if not treffer:
        return None
    roh = treffer.group(0)
    for _ in range(SUMMARY_JSON_REPAIR_LINES + 1):
        try:
            return json.loads(roh)
        except json.JSONDecodeError as e:
            anfang = roh.rfind("\n", 0, e.pos) + 1
            ende = roh.find("\n", e.pos)
            if anfang == 0 or ende == -1:
                return None
            roh = roh[:anfang] + roh[ende + 1:]
    return None


def _stamm(name: str) -> str:
    """A file name without extension and case, how a model tends to repeat it."""
    return name.rsplit(".", 1)[0].casefold() if "." in name else name.casefold()


def _names(roh, dateien: list[str] | None) -> dict[str, str]:
    """The short names the plan gave the files, a name that is the file name itself is none.

    A file the model wrote without extension still counts. When no entry names a known file
    at all but there is one per file, the order of the list decides.
    """
    dateien = dateien or []
    eintraege = [(str(e.get("file") or "").strip(), " ".join(str(e.get("short_name") or "").split()))
                 for e in (roh if isinstance(roh, list) else []) if isinstance(e, dict)]
    nach_stamm = {_stamm(d): d for d in dateien}
    zuordnung = [(nach_stamm.get(_stamm(f)), k) for f, k in eintraege]
    if not any(d for d, _ in zuordnung) and len(eintraege) == len(dateien):
        zuordnung = [(d, k) for d, (_, k) in zip(dateien, eintraege)]
    return {d: k for d, k in zuordnung
            if d and k and len(k) <= 40 and _stamm(k) != _stamm(d)}


def parse_outline(raw: str | None, stellen=None, dateien: list[str] | None = None,
                  anker=None, extra: list[str] | None = None,
                  minimum: int = SUMMARY_MIN_SECTIONS) -> Outline:
    """Reads the planning answer, a broken one yields no sections rather than an error.

    Headings and the numbers under them come out of the same call. ``stellen`` turns the
    refs of a section into passage numbers, invented ones drop out there. ``anker`` moves
    them to where the section's copied first words stand.
    """
    roh = loose_json(_strip_thinking(raw))
    if not isinstance(roh, dict):
        return Outline()
    rohe = roh.get("sections")
    if rohe is not None and not isinstance(rohe, list):
        return Outline()
    abschnitte: list[Section] = []
    for eintrag in rohe or []:
        titel = (eintrag.get("title") if isinstance(eintrag, dict) else eintrag) or ""
        umfang = (eintrag.get("scope") or eintrag.get("description")
                  if isinstance(eintrag, dict) else "") or ""
        titel = " ".join(str(titel).split()).lstrip("#").strip()
        if not titel or len(titel) > 120:
            continue
        if any(a.title.casefold() == titel.casefold() for a in abschnitte):
            continue
        refs = eintrag.get("refs") if isinstance(eintrag, dict) else None
        nummern = stellen(refs) if stellen else []
        if anker is not None and isinstance(eintrag, dict):
            nummern = anker(nummern, eintrag.get("start"))
        abschnitte.append(Section(title=titel, scope=" ".join(str(umfang).split()),
                                  stellen=nummern))
    if len(abschnitte) < minimum:
        return Outline()
    titel = " ".join(str(roh.get("title") or "").split()).lstrip("#").strip()
    return Outline(title=titel[:120], intro=str(roh.get("intro") or "").strip(),
                   sections=abschnitte[:SUMMARY_MAX_SECTIONS],
                   names=_names(roh.get("documents"), dateien),
                   extra={k: roh[k] for k in extra or [] if k in roh})


def _outline_system(language: str, template_body: str, target: int, sources: int,
                    modus: str = "stellen", span: tuple[int, int] | None = None,
                    fokus: bool = False, extra_rules: str = "") -> str:
    from src.services.text_map import hinweis

    lo, hi = span or (SUMMARY_MIN_SECTIONS, SUMMARY_MAX_SECTIONS)
    return (
        "You plan a document out of numbered material. The numbers are working material, "
        "the reader never sees them. You decide the headings AND which numbers go under "
        "each of them.\n" + hinweis(modus) + "\n"
        + GROUND_RULES.format(language=language) + "\n"
        "Rule 8: Derive every section from what the material carries. Never fall back on a "
        "generic scaffold such as introduction, main part, conclusion.\n"
        f"Rule 9: Plan around {target} sections, between {lo} and {hi}. Thin material "
        "gets fewer, rich material gets more.\n"
        "Rule 10: A heading names a theme that carries several numbers, never a single one. "
        "If a heading would rest on one statement alone, widen it or fold it into another.\n"
        + (("Rule 11: The instruction at the end names the subject of the document. Plan only "
            "sections on it and leave out every file and every part of the BUILD PLAN the "
            "material says nothing on for this subject. Work through the whole material to its "
            "last number to find everything it says on the subject.\n") if fokus else
           (f"Rule 11: The material comes from {sources} file(s), listed below, and EVERY one of "
            "them must be covered by at least one section. Work through the whole material "
            "to its last number before you settle the headings. A subject only the later numbers "
            "carry still needs its own heading.\n")) +
        "Rule 12: Sections must not overlap, and the headings follow the subject, never the "
        "file the material came from. A heading never names a file.\n"
        "Rule 13: Plan the sections the BUILD PLAN below asks for. Where it names parts the "
        "result must have, such as a quiz, an answer key or a glossary, each is a section of "
        "its own, and a part that answers another one comes after it. Where it asks for an "
        "order, such as what the reader must act on first and background last, the sections "
        "are already in that order.\n"
        "Rule 14a: Every section names the numbers it rests on under refs. Together the "
        + ("sections cover what the material says on the subject" if fokus else
           "sections cover everything that carries content")
        + ", and a number rarely belongs to two sections.\n"
        "Rule 14: The title names what the material is about, short, and never mentions a "
        "file or the format.\n"
        "Rule 15: The intro stands before the first heading. Its first sentence says what "
        "the material covers, then come the three to five most important things it states, "
        "concretely and with their figures. Never say what the reader will receive and never "
        "repeat these instructions.\n"
        "Rule 16: Under documents, give every file the short name its own text uses for "
        "itself, such as a law's abbreviation, else a title of two to four words. The "
        "beginning of each file is shown next to it. Never use the file name.\n"
        + extra_rules
        + "\nBUILD PLAN\n" + template_body
    )


def _instruction(instructions: str) -> str:
    """The person's own wish for a writer, placed last so it gets the attention, the rules still win."""
    return "\n" + anweisung.schreib_zusatz(instructions, anweisung.STIL) if instructions.strip() else ""


def _outline_user(sources: list[str], material: str, fehlt: list[str] | None = None,
                  anfaenge: list[str] | None = None, instructions: str = "",
                  weg: str = "") -> str:
    anfaenge = anfaenge or []
    liste = "\n".join(
        f"- {s}" + (f", begins with: {' '.join(anfaenge[i].split())}" if i < len(anfaenge) else "")
        for i, s in enumerate(sources))
    mahnung = ("\nYOUR LAST PLAN GAVE THESE FILES FAR TOO LITTLE ROOM. Give each a share of "
               "the sections and refs that matches how much of the material it holds: "
               + ", ".join(fehlt) + "\n") if fehlt else ""
    zusatz = anweisung.plan_zusatz(instructions, weg, "section")
    return (f"/no_think\nSources:\n{liste}\n{mahnung}\nMATERIAL:\n\n{material}"
            + ("\n" + zusatz if zusatz else ""))


async def plan_outline(caller: Caller, *, language: str, template_body: str,
                       sources: list[str], material: str, target: int,
                       modus: str = "stellen", stellen=None,
                       span: tuple[int, int] | None = None,
                       fehlt: list[str] | None = None,
                       anfaenge: list[str] | None = None,
                       instructions: str = "", weg: str = "", anker=None,
                       extra_fields: dict | None = None, extra_rules: str = "",
                       enforce_schema: bool = True) -> Outline:
    """Plans the headings of the document. Empty when planning failed.

    ``extra_fields`` are further schema fields a tool wants from the same call, so it saves a
    call of its own, ``extra_rules`` say how to fill them. Without ``enforce_schema`` the shape
    is only described, the model then writes the plan faster and never runs on in blank lines.
    """
    erzwungen = {"response_format": outline_schema(extra_fields)} if enforce_schema else {}
    form = "" if enforce_schema else "\n" + outline_shape(extra_fields)
    plan = Outline()
    # Short material carries fewer headings than the usual floor, one is enough there.
    minimum = (SUMMARY_MIN_SECTIONS
               if len(material) >= SUMMARY_MIN_SECTIONS * SUMMARY_CHARS_PER_SECTION else 1)
    for versuch in range(1, SUMMARY_OUTLINE_MAX_ATTEMPTS + 1):
        try:
            antwort = await caller.create(
                messages=[
                    {"role": "system",
                     "content": _outline_system(language, template_body, target, len(sources),
                                                modus, span, anweisung.fokus(instructions, weg),
                                                extra_rules) + form},
                    {"role": "user",
                     "content": _outline_user(sources, material, fehlt, anfaenge, instructions,
                                              weg)},
                ],
                temperature=0.2, name=f"outline:{versuch}",
                max_tokens=SUMMARY_OUTLINE_MAX_TOKENS, **erzwungen,
            )
            plan = parse_outline(antwort.choices[0].message.content, stellen, sources, anker,
                                 list(extra_fields or {}), minimum=minimum)
            # Without a single passage the writers would have nothing to write from.
            if stellen and not any(a.stellen for a in plan.sections):
                plan = Outline()
            if plan.sections:
                break
            logger.warning("Zusammenfassung: Gliederung {} unlesbar", versuch)
        except Exception as e:  # noqa: BLE001 - the single call still saves the run
            if is_provider_refusal(e):
                raise
            logger.warning("Zusammenfassung: Planungsaufruf {} gescheitert ({})", versuch, e)
        if versuch < SUMMARY_OUTLINE_MAX_ATTEMPTS:
            await asyncio.sleep(SUMMARY_RETRY_DELAY_SECONDS)
    return plan


def _finished(antwort) -> str:
    """The written text, a half line the cap cut off is dropped."""
    wahl = antwort.choices[0]
    text = _strip_thinking(wahl.message.content)
    if getattr(wahl, "finish_reason", None) == "length":
        text = cut_to_last_line(text)
    if not text:
        raise RuntimeError("Das Modell hat nichts geantwortet.")
    return text


def _drop_leading_heading(text: str) -> str:
    """Cuts one leading Markdown heading, the rule against it is a request, not a guarantee."""
    zeilen = text.split("\n")
    if not zeilen or not re.match(r"^#{1,6}\s+\S", zeilen[0]):
        return text
    zeilen = zeilen[1:]
    while zeilen and not zeilen[0].strip():
        zeilen.pop(0)
    return "\n".join(zeilen)


def group_sections(sections: list[Section], costs: list[int],
                   budget: int | None = None) -> list[list[int]]:
    """Runs of neighbouring sections that fit one writing call, by their expected prose.

    Small sections cost a whole call each while using a fraction of the answer, so they
    travel together. A section too big on its own still gets its own call.
    """
    if budget is None:
        budget = SUMMARY_SECTION_GROUP_CHARS
    gruppen: list[list[int]] = []
    laufend: list[int] = []
    summe = 0
    for i, abschnitt in enumerate(sections):
        kosten = costs[i] if i < len(costs) else SUMMARY_SECTION_BASE_CHARS
        if laufend and summe + kosten > budget:
            gruppen.append(laufend)
            laufend, summe = [], 0
        laufend.append(i)
        summe += kosten
    if laufend:
        gruppen.append(laufend)
    return gruppen


def _heading_positions(text: str) -> list[tuple[int, int, str]]:
    """Every level two heading: where its line starts, where its body starts, its wording."""
    return [(m.start(), m.end(), m.group(1).strip())
            for m in re.finditer(r"^##+[ \t]+(.+)$", text, re.M)]


def split_group(text: str, titles: list[str]) -> list[str] | None:
    """The text of each section of a group, or None when the answer cannot be cut safely.

    Matched by wording first, by position only when the count is exactly right. A wrong cut
    would put one section's prose under another's heading, so None is the honest answer.
    """
    if len(titles) == 1:
        return [text.strip()]
    koepfe = _heading_positions(text)
    if not koepfe:
        return None
    gewaehlt: list[tuple[int, int, str]] = []
    suche = 0
    for titel in titles:
        treffer = next((k for k in koepfe[suche:]
                        if k[2].casefold() == titel.casefold()), None)
        if treffer is None:
            gewaehlt = []
            break
        gewaehlt.append(treffer)
        suche = koepfe.index(treffer) + 1
    if not gewaehlt:
        if len(koepfe) != len(titles):
            return None
        gewaehlt = koepfe
    teile: list[str] = []
    for nr, (_, koerper_ab, _) in enumerate(gewaehlt):
        ende = gewaehlt[nr + 1][0] if nr + 1 < len(gewaehlt) else len(text)
        teile.append(text[koerper_ab:ende].strip())
    return teile if all(teile) else None


_NO_REPEATED_BULLETS = (
    "Never begin two bullets with the same words or the same subject, such as the same "
    "actor, document or term. Write that subject once as a bullet of its own and put what is "
    "said about it in sub bullets under it, indented by two spaces, each one going on without "
    "repeating the subject. Instead of '- The employer must X' and '- The employer must Y' "
    "write '- The employer' with the sub bullets '  - must X' and '  - must Y'."
)


def _section_system(language: str, template_body: str, count: int = 1,
                    sees_document: bool = True) -> str:
    mehrere = (
        f"You write {count} CONSECUTIVE sections of a larger document. Begin each one with "
        "its heading exactly as given, on its own line, written as '## Heading'. Write "
        "nothing before the first heading and nothing after the last section. Every heading "
        "you write is one of the given ones, never an extra one of your own.\n"
        if count > 1 else
        "You write ONE section of a larger document. Do not write the heading.\n"
    )
    return (
        mehrere
        + ("The sections before yours are already written and given to you, the ones after "
           "yours come later.\n" if sees_document else
           "The other sections are written at the same time by others, their headings and "
           "scopes are listed.\n")
        + GROUND_RULES.format(language=language) + "\n"
        "Rule 8: Write only what belongs under the heading you are writing. The scopes of the "
        "other sections are listed so you stay off their ground. Never announce what "
        "comes later.\n"
        + ("Rule 9: Continue the document you are given, never repeat what it already says. "
           "Where your section answers or builds on an earlier one, make the two match item "
           "for item.\n" if sees_document else
           "Rule 9: Never write what belongs under another section's heading, the reader "
           "finds it there.\n")
        + "Rule 10: Go as deep as the material allows. A Markdown table where things are compared "
        "along the same attributes, bullet points where it is a list, numbered items where "
        "order or count matters, continuous text where it is an argument.\n"
        "Rule 10a: " + _NO_REPEATED_BULLETS + "\n"
        "Rule 11: A figure, a date or a quantity never stands without what it refers to, and "
        "you carry over every one the material states for your heading.\n"
        "Rule 12: Your material is passages of the original text, each under a line in "
        "square brackets naming its file and page. That line is for orientation only, never "
        "copy it, and its page number is never the number of a paragraph or article. Where the text itself names a part such as a paragraph or article, keep "
        "that name exactly as it stands, never number a part yourself.\n"
        "Rule 13: Two passages saying the same thing become ONE statement, in the fuller "
        "wording. Never write the same figure or duty twice in different words.\n"
        "Rule 14: The passages also carry some text around what your heading needs. Use "
        "everything that belongs under your heading and leave out what belongs elsewhere.\n"
        "Rule 15: What the material marks as open or disputed stays in, marked as such.\n"
        + ("Rule 16: Under each heading begin straight with the content, no lead in, no "
           "closing remark and no greeting.\n" if count > 1 else
           "Rule 16: Do not repeat your own heading. Begin with the content, write no closing "
           "remark and no greeting.\n")
        + "Rule 17: Never cite a page, a slide or a position, and never quote the passages "
        "as a block. Never name a file and never write a file name into your text. A "
        "document may be named by the short name its own text uses, such as a law's "
        "abbreviation.\n"
        "\nThe document as a whole follows the build plan below. Match its register, but "
        "produce ONLY the sections you are given.\n\nBUILD PLAN\n" + template_body
    )


def _document_so_far(written: list[tuple[str, str]]) -> str:
    """The sections already written, the newest in full, the oldest dropped when it is tight."""
    bisher = "\n\n".join(f"## {titel}\n{text}" for titel, text in written) \
        or "(nothing yet, yours is the first section)"
    if len(bisher) <= SUMMARY_PROMPT_RESERVE_CHARS:
        return bisher
    # The headings stay in full, the oldest prose goes, the newest is what matters.
    koepfe = "\n".join(f"## {titel}" for titel, _ in written)
    uebrig = max(0, SUMMARY_PROMPT_RESERVE_CHARS - len(koepfe))
    rest = bisher[-uebrig:] if uebrig else ""
    return f"{koepfe}\n\n[...]\n{rest}"


def _section_user(group: list[Section], others: list[Section],
                  written: list[tuple[str, str]] | None, facts: list[str],
                  words: int | None = None, names: dict[str, str] | None = None,
                  instructions: str = "") -> str:
    """The order matters: what is to be written comes last, that is what gets the attention.

    Without ``written`` the section is one of several written at the same time.
    """
    fremd = "\n".join(f"- {a.title}: {a.scope}" for a in others) or "- none"
    laenge = (f"LENGTH: about {words} words for each section, never more than "
              f"{words * 3 // 2}. Choose what matters most to fit.\n\n") if words else ""
    if names:
        laenge += ("DOCUMENT NAMES, use these and never a file name:\n"
                   + "\n".join(f"- {d} = {k}" for d, k in names.items()) + "\n\n")
    if len(group) == 1:
        kopf = f"YOUR HEADING: {group[0].title}\nYOUR SCOPE: {group[0].scope}\n\n"
        auftrag = f"YOUR MATERIAL:\n\n{facts[0]}"
    else:
        kopf = f"YOU WRITE {len(group)} SECTIONS, in the order below.\n\n"
        teile = [f"=== SECTION {i + 1} OF {len(group)} ===\n"
                 f"HEADING: {a.title}\nSCOPE: {a.scope}\nMATERIAL:\n{f}"
                 for i, (a, f) in enumerate(zip(group, facts))]
        auftrag = "YOUR SECTIONS:\n\n" + "\n\n".join(teile)
    if written is None:
        return (f"/no_think\n{kopf}Written by others, stay off these:\n{fremd}\n\n"
                f"{laenge}{auftrag}" + _instruction(instructions))
    return (
        "/no_think\n"
        f"{kopf}"
        f"Still to be written by others, stay off these:\n{fremd}\n\n"
        f"THE DOCUMENT SO FAR:\n{_document_so_far(written)}\n\n"
        f"{laenge}{auftrag}" + _instruction(instructions)
    )


async def write_sections(caller: Caller, *, language: str, template_body: str,
                         group: list[Section], others: list[Section],
                         written: list[tuple[str, str]] | None, material: list[str],
                         budget: int, words: int | None = None,
                         names: dict[str, str] | None = None,
                         instructions: str = "") -> list[str] | None:
    """Writes a run of sections in one call, None when the answer cannot be cut apart.

    None is not a failure of the run: the caller then writes the sections one at a time,
    which costs calls but never mixes one section's prose into another's heading.
    """
    antwort = await caller.create(
        messages=[
            {"role": "system", "content": _section_system(
                language, template_body, len(group), sees_document=written is not None)},
            {"role": "user",
             "content": _section_user(group, others, written, material, words, names,
                                      instructions)},
        ],
        temperature=0.3,
        name=f"section:{group[0].title}" if len(group) == 1
        else f"sections:{len(group)}:{group[0].title}",
        max_tokens=SUMMARY_WRITE_MAX_TOKENS,
    )
    fertig = _finished(antwort)
    if len(group) == 1:
        # Cut here, not in assemble: a stored heading would keep teaching the pattern back.
        text = _drop_leading_heading(fertig)
        return [text] if text else None
    return split_group(fertig, [a.title for a in group])


def _compose_system(language: str, template_body: str) -> str:
    return (
        "You write the finished document from the numbered text of several sources.\n"
        + GROUND_RULES.format(language=language) + "\n"
        "Rule 8: Begin immediately with the content, no framing sentence, no closing remark.\n"
        "Rule 9: Follow the build plan below exactly, it decides the shape. About "
        "faithfulness, the rules above win.\n"
        "Rule 10: A figure, a date or a quantity never stands without what it refers to.\n"
        "Rule 11: The numbers in square brackets are for orientation only, never copy them.\n"
        "Rule 12: Two passages saying the same thing become ONE statement, in the fuller wording.\n"
        "Rule 13: What the material marks as open or disputed stays in, marked.\n"
        "Rule 14: Never cite a page, a slide or a position. Never name "
        "a file and never write a file name into your text.\n"
        "Rule 15: Write ONE document covering all sources together, never one section per "
        "file unless the build plan asks for it, and every source is represented.\n"
        "Rule 16: " + _NO_REPEATED_BULLETS + "\n"
        "\nBUILD PLAN\n" + template_body
    )


async def compose_single(caller: Caller, *, language: str, template_body: str,
                         sources: list[str], material: str, instructions: str = "",
                         weg: str = "") -> str:
    """The whole document in one call, the fallback for a failed outline.

    Tried more than once on purpose, one dropped call must not end the run. What still
    fails after the last attempt is raised, so the stage fails visibly.
    """
    for versuch in range(1, SUMMARY_COMPOSE_MAX_ATTEMPTS + 1):
        try:
            antwort = await caller.create(
                messages=[
                    {"role": "system", "content": _compose_system(language, template_body)},
                    {"role": "user",
                     "content": _outline_user(sources, material, instructions=instructions,
                                              weg=weg)},
                ],
                temperature=0.3, name=f"compose:{versuch}",
                max_tokens=SUMMARY_WRITE_MAX_TOKENS,
            )
            return _finished(antwort)
        except Exception as e:  # noqa: BLE001 - the last attempt hands the failure on
            if is_provider_refusal(e):
                raise
            logger.warning("Zusammenfassung: Einzelaufruf {} gescheitert ({})", versuch, e)
            if versuch >= SUMMARY_COMPOSE_MAX_ATTEMPTS:
                raise
            await asyncio.sleep(SUMMARY_RETRY_DELAY_SECONDS)
    raise RuntimeError("Der Einzelaufruf hat nichts geliefert.")


def assemble(intro: str, titles: list[str], texts: list[str], headings: bool,
             title: str = "") -> str:
    """Joins the written sections, with or without their headings.

    The document title only goes in where the build plan allows headings at all: a plan
    asking for one continuous text gets no heading of any level.
    """
    teile = [f"# {title.strip()}"] if title.strip() and headings else []
    if intro.strip():
        teile.append(intro.strip())
    for titel, text in zip(titles, texts):
        koerper = (text or "").strip()
        if not koerper:
            continue
        teile.append(f"## {titel}\n\n{koerper}" if headings else koerper)
    return "\n\n".join(teile)


def split_title(text: str) -> tuple[str, str]:
    """The document's own title and the body without it, ("", text) when it carries none.

    The Word cover page shows the title, so leaving it in the body would print it twice.
    """
    zeilen = text.split("\n")
    if not zeilen or not re.match(r"^#\s+\S", zeilen[0]):
        return "", text
    titel = zeilen[0].lstrip("#").strip()
    rest = zeilen[1:]
    while rest and not rest[0].strip():
        rest.pop(0)
    return titel, "\n".join(rest)

