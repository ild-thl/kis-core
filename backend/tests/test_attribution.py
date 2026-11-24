"""After-the-fact evidence search for overview answers, with a distance threshold."""
from src.features.ai_assistant.routes._chips import _attribution_chip, _lead_in_lines
from src.features.ai_assistant.routes._evidence import (
    _attribute_generic_text,
    _attribution_subunits,
    _enum_chip_unbacked,
    _names_many_laws,
    _pick_attribution,
)
from src.features.ai_assistant.routes._refusal import _cos_dist, _refusal_lines, is_refusal_answer
from src.features.ai_assistant.prompts.refusal_prompts import (
    RAG_NO_INFO_SENTINEL,
    is_sentinel_refusal,
)


def _hit(sid, page, content, dist, start=None):
    return {"source_id": sid, "page_number": page, "content": content,
            "vec_distance": dist, "start_time": start}


# ── _pick_attribution (distance gate) ────────────────────────────────────────

def test_picks_closest_within_gate():
    hits = [_hit(1, 5, "a", 0.45), _hit(1, 7, "b", 0.20)]
    assert _pick_attribution(hits, 0.6)["page_number"] == 7  # closest wins


def test_rejects_when_all_too_far():
    hits = [_hit(1, 5, "a", 0.80), _hit(1, 7, "b", 0.75)]
    assert _pick_attribution(hits, 0.6) is None


def test_empty_hits_returns_none():
    assert _pick_attribution([], 0.6) is None


def test_ignores_hits_without_distance():
    assert _pick_attribution([{"source_id": 1, "page_number": 5}], 0.6) is None


# ── _attribution_chip (nav-only: page or timestamp, no offset/keyword) ───────

def test_attribution_chip_is_nav_only_pdf():
    assert _attribution_chip(2, _hit(1, 12, "x", 0.2), "line") == ["[2, S. 12]"]


def test_attribution_chip_is_nav_only_media():
    chunk = {"source_id": 3, "page_number": None, "content": "x", "vec_distance": 0.2, "start_time": 92.0}
    assert _attribution_chip(3, chunk, "line") == ["[3, 01:32]"]


def test_attribution_chip_media_with_segment_page_uses_timestamp():
    # For audio and video the chip has to carry the timestamp, never the segment number.
    chunk = {"source_id": 3, "page_number": 9, "content": "x", "vec_distance": 0.2, "start_time": 92.0}
    assert _attribution_chip(3, chunk, "line") == ["[3, 01:32]"]


# Otherwise the chunk start time points at the greeting instead of the sentence.

_SEGMENTE = [
    {"start": 0.0, "end": 24.0, "text": "Die machen wir auch noch. Aber so weit sind wir ja noch nicht."},
    {"start": 30.0, "end": 59.0, "text": "Wir befassen uns heute mit der Binomialverteilung."},
    {"start": 117.0, "end": 128.0, "text": "Wir machen sich das Komplementieren mit dem Strich darüber."},
]


def _chunk_aus(segmente: list[dict]) -> dict:
    """A media chunk the way chunking builds it."""
    return {
        "source_id": 8, "page_number": 1, "vec_distance": 0.2,
        "start_time": segmente[0]["start"], "end_time": segmente[-1]["end"],
        "content": " ".join(s["text"] for s in segmente),
    }


_LANGSAMER_CHUNK = _chunk_aus(_SEGMENTE)


def test_media_chip_points_at_the_segment_that_carries_the_line():
    out = _attribution_chip(8, _LANGSAMER_CHUNK, "Ein **Strich** darüber", _SEGMENTE)
    assert out == ["[8, 01:57]"]


def test_media_chip_matches_across_inflection():
    # The model inflects anew, an exact word comparison would fall behind.
    segs = [
        {"start": 0.0, "end": 24.0, "text": "Die machen wir auch noch."},
        {"start": 128.0, "end": 140.0,
         "text": "Einige machen das mit einem großen C, also einem länglichen C vor dem A."},
    ]
    out = _attribution_chip(8, _chunk_aus(segs), "Ein **großes C** (ein längliches C) vor dem A", segs)
    assert out == ["[8, 02:08]"]


def test_media_chip_counts_a_short_number_as_a_feature():
    """In spoken text a number is the most discriminating feature."""
    segs = [
        {"start": 0.0, "end": 29.0, "text": "Startet doch jetzt, Leute, der rote Punkt."},
        {"start": 30.0, "end": 46.0, "text": "Das sind die Lösungen, die zeigen wir auch noch."},
        {"start": 60.0, "end": 72.0, "text": "So, das ist die Klausur 8.9."},
        {"start": 450.0, "end": 469.0, "text": "Dann können Sie jetzt die Klausur sehen."},
    ]
    out = _attribution_chip(8, _chunk_aus(segs),
                            "In einer Aufzeichnung wird eine Klausur vom 8.9. gezeigt.", segs)
    assert out == ["[8, 01:00]"]


def test_media_chip_still_needs_two_features_with_a_number():
    """The number does not replace the two-hit rule, it only counts along."""
    segs = [
        {"start": 0.0, "end": 29.0, "text": "Guten Morgen, wir fangen an."},
        {"start": 60.0, "end": 72.0, "text": "Seite 8.9 im Skript."},
    ]
    out = _attribution_chip(8, _chunk_aus(segs), "Es geht um 8.9.", segs)
    assert out == ["[8, 00:00]"]


def test_media_chip_falls_back_to_chunk_start_without_segments():
    assert _attribution_chip(8, _LANGSAMER_CHUNK, "Ein Strich darüber") == ["[8, 00:00]"]


def test_media_chip_falls_back_when_no_segment_carries_the_line():
    out = _attribution_chip(8, _LANGSAMER_CHUNK, "Verpflichtete nach dem Geldwaeschegesetz", _SEGMENTE)
    assert out == ["[8, 00:00]"]


def test_media_chip_ignores_a_single_matching_word():
    # A single word stem is not enough, better the known chunk start.
    out = _attribution_chip(8, _LANGSAMER_CHUNK,
                            "Die Binomialverteilung beschreibt wiederholte Zufallsversuche",
                            _SEGMENTE)
    assert out == ["[8, 00:00]"]


def test_media_chip_marks_the_start_of_a_sentence_split_across_segments():
    # The chip belongs at the sentence start, even when more words match later.
    segs = [
        {"start": 0.0, "end": 40.0, "text": "Voellig anderes Thema ohne Bezug."},
        {"start": 104.0, "end": 117.0, "text": "Wir machen das Komplementieren mit dem Strich"},
        {"start": 117.0, "end": 128.0, "text": "darüber, zwei Schreibweisen."},
    ]
    out = _attribution_chip(8, _chunk_aus(segs),
                            "Zwei Schreibweisen: Komplementieren mit dem Strich darüber", segs)
    assert out == ["[8, 01:44]"]


# ── _attribute_generic_text (orchestration, injected search) ─────────────────

def _searcher(mapping):
    # mapping: line-substring -> hits
    def search_one(line):
        for key, hits in mapping.items():
            if key in line:
                return hits
        return []
    return search_one


def test_attributes_supported_line_nav_only():
    line = "Das Modul behandelt Audio Grafik und Video."
    search = _searcher({"Audio Grafik": [_hit(1, 12, "Audio Grafik und Video Kernmedien", 0.2)]})
    out = _attribute_generic_text(line, search, {1: 2}, max_distance=0.6)
    assert out == "Das Modul behandelt Audio Grafik und Video [2, S. 12]."


def test_no_chip_when_unsupported():
    line = "Diese Aussage steht so nicht in den Quellen."
    search = _searcher({"Aussage": [_hit(1, 5, "irrelevant", 0.9)]})  # too far
    assert _attribute_generic_text(line, search, {1: 1}, max_distance=0.6) == line


def test_short_line_untouched():
    assert _attribute_generic_text("## Überblick", _searcher({}), {1: 1}) == "## Überblick"


def test_already_cited_line_untouched():
    line = "Fakt mit Quelle hier drin. [1, S. 3 | Fakt]"
    out = _attribute_generic_text(line, _searcher({"Fakt": [_hit(1, 9, "x", 0.1)]}), {1: 1})
    assert out == line


def test_unknown_source_qnum_no_chip():
    line = "Eine inhaltlich substanzielle Aussage zum Thema."
    search = _searcher({"substanzielle": [_hit(99, 5, "Aussage zum Thema", 0.2)]})
    # source_id 99 not in the qmap -> no chip
    assert _attribute_generic_text(line, search, {1: 1}, max_distance=0.6) == line


def test_offset_fn_positional_ignored():
    """offset_fn may still be passed as a positional arg (legacy caller) — must not crash."""
    line = "Das Modul behandelt Audio Grafik und Video."
    search = _searcher({"Audio Grafik": [_hit(1, 12, "Audio Grafik und Video Kernmedien", 0.2)]})
    dummy_offset_fn = lambda sid, page, ln: [" @5-30 | Audio Grafik und Video"]
    out = _attribute_generic_text(line, search, {1: 2}, dummy_offset_fn, max_distance=0.6)
    # offset_fn is ignored -> nav-only chip, NOT an offset chip
    assert out == "Das Modul behandelt Audio Grafik und Video [2, S. 12]."


# ── cross-check: only chip when the source/page was actually retrieved ────────

def test_crosscheck_accepts_retrieved_page():
    line = "Eine inhaltlich substanzielle Aussage zum Thema hier."
    out = _attribute_generic_text(line, _searcher({"substanzielle": [_hit(1, 12, "x", 0.2)]}),
                                  {1: 2}, seen_pages_by_source={1: {12}}, max_distance=0.6)
    assert out == f"{line[:-1]} [2, S. 12]."


def test_crosscheck_drops_unretrieved_page():
    line = "Eine inhaltlich substanzielle Aussage zum Thema hier."
    out = _attribute_generic_text(line, _searcher({"substanzielle": [_hit(1, 99, "x", 0.2)]}),
                                  {1: 2}, seen_pages_by_source={1: {12}}, max_distance=0.6)
    assert out == line


def test_crosscheck_drops_source_not_in_seen_map():
    # source 5 never appeared in retrieval -> seen_pages_by_source has no key for it -> reject
    line = "Eine inhaltlich substanzielle Aussage zum Thema hier."
    out = _attribute_generic_text(line, _searcher({"substanzielle": [_hit(5, 3, "x", 0.2)]}),
                                  {5: 2}, seen_pages_by_source={1: {12}}, max_distance=0.6)
    assert out == line


def test_crosscheck_media_passes_when_source_retrieved():
    line = "Eine inhaltlich substanzielle Aussage zum Thema hier."
    hit = {"source_id": 3, "page_number": None, "content": "x", "vec_distance": 0.2, "start_time": 92.0}
    out = _attribute_generic_text(line, _searcher({"substanzielle": [hit]}),
                                  {3: 1}, seen_pages_by_source={3: set()}, max_distance=0.6)
    assert out == f"{line[:-1]} [1, 01:32]."


def test_crosscheck_media_with_segment_page_passes():
    # Media sources have an empty page set, the chip still has to get through.
    line = "Eine inhaltlich substanzielle Aussage zum Thema hier."
    hit = {"source_id": 3, "page_number": 9, "content": "x", "vec_distance": 0.2, "start_time": 92.0}
    out = _attribute_generic_text(line, _searcher({"substanzielle": [hit]}),
                                  {3: 1}, seen_pages_by_source={3: set()}, max_distance=0.6)
    assert out == f"{line[:-1]} [1, 01:32]."


def test_no_crosscheck_when_not_passed():
    line = "Eine inhaltlich substanzielle Aussage zum Thema hier."
    out = _attribute_generic_text(line, _searcher({"substanzielle": [_hit(1, 7, "x", 0.2)]}),
                                  {1: 2}, max_distance=0.6)
    assert out == f"{line[:-1]} [2, S. 7]."


def test_table_header_not_cited_and_data_chip_inside_cell():
    # In a table the chip goes into the last cell, the header row stays free.
    table = (
        "| Datum der Veranstaltung | Termin und Uhrzeit |\n"
        "|---|---|\n"
        "| 01.04.2026 | Webkonferenz Einfuehrung zum Seminar |"
    )
    out = _attribute_generic_text(
        table,
        _searcher({"Datum": [_hit(1, 6, "x", 0.2)], "Webkonferenz": [_hit(1, 6, "x", 0.2)]}),
        {1: 1}, seen_pages_by_source={1: {6}}, max_distance=0.6,
    )
    lines = out.split("\n")
    assert lines[0] == "| Datum der Veranstaltung | Termin und Uhrzeit |"  # header NOT cited
    assert lines[1] == "|---|---|"                                         # delimiter untouched
    assert lines[2].rstrip().endswith("|")                                 # row still closes with a pipe
    assert "[1, S. 6]" in lines[2]                                         # chip present
    assert lines[2].count("|") == 3                                        # same column count as a clean 2-col row


def test_guarantee_chips_grounded_answer_borderline_block():
    # A block just behind the threshold gets its chip too.
    text = ("- Erste klar belegte Aussage zum Thema hier.\n"
            "- Zweite Aussage etwas vager formuliert hier.")
    search = _searcher({
        "klar belegte": [_hit(1, 5, "x", 0.2)],
        "vager formuliert": [_hit(1, 8, "y", 0.7)],
    })
    out = _attribute_generic_text(text, search, {1: 1},
                                  seen_pages_by_source={1: {5, 8}}, max_distance=0.6)
    assert "[1, S. 5]" in out
    assert "[1, S. 8]" in out          # guaranteed despite 0.7 > 0.6 gate


def test_chips_at_block_end_not_mid_bullet():
    # The chips go to the block end, never into the middle of a bullet.
    text = ("- **Artikel 1 schützt die Würde des Menschen.**\n"
            " Dieser Artikel verpflichtet alle staatliche Gewalt dazu.")
    search = _searcher({
        "Würde des Menschen": [_hit(1, 1, "x", 0.2)],
        "staatliche Gewalt": [_hit(1, 1, "y", 0.3)],
    })
    out = _attribute_generic_text(text, search, {1: 2},
                                  seen_pages_by_source={1: {1}}, max_distance=0.6)
    lines = out.split("\n")
    assert "[2, S. 1]" not in lines[0]   # NO chip mid-bullet (after the first line)
    assert "[2, S. 1]" in lines[1]       # chip only at the block END
    assert out.count("[2, S. 1]") == 1   # deduped across the block


def test_multi_chip_two_close_pages_both_cited():
    # Two pages practically equally far away, real co-sources, so two chips.
    line = "Eine zusammengesetzte Aussage aus mehreren Stellen zugleich."
    search = _searcher({"zusammengesetzte": [_hit(1, 5, "x", 0.30), _hit(1, 9, "y", 0.33)]})
    out = _attribute_generic_text(line, search, {1: 1},
                                  seen_pages_by_source={1: {5, 9}}, max_distance=0.6)
    assert "[1, S. 5]" in out and "[1, S. 9]" in out


def test_multi_chip_drops_far_secondary_relative_gate():
    # The distance rule keeps only the best hit, no near misses.
    line = "Die Löschung der Eintragung in die Handwerksrolle ist unter Bedingungen möglich."
    search = _searcher({"Löschung der Eintragung": [
        _hit(1, 10, "real source", 0.21),
        _hit(1, 9, "weakly related", 0.32),
        _hit(1, 58, "off-topic noise", 0.33),
    ]})
    out = _attribute_generic_text(line, search, {1: 1},
                                  seen_pages_by_source={1: {9, 10, 58}}, max_distance=0.6)
    assert "[1, S. 10]" in out
    assert "[1, S. 9]" not in out and "[1, S. 58]" not in out
    assert out.count("[1,") == 1   # exactly one chip


# The distance applies to a second source too, no free pass any more.
_DEADLINE = "Die finale Abgabe der Hausarbeit ist am 3. Juli 2026 fällig"
_TALK_0858 = "der 3. Juli, da ist die finale Deadline, wann Sie einreichen"
# The date stands as one number so the number exception does not apply.
_SLIDE_DEADLINE = "Abgabe der Hausarbeit bis 03.07.2026"
# A course corpus: 'Abgabe' and 'Hausarbeit' appear on almost every chunk.
_COURSE = [{"content": f"Kapitel {n}: Hinweise zur Abgabe der Hausarbeit im Modul."}
           for n in ("eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht",
                     "neun", "zehn")]


def test_multi_chip_other_source_needs_equal_distance_too():
    hits = [_hit(1, 41, _TALK_0858, 0.31, start=538.0), _hit(3, 4, _SLIDE_DEADLINE, 0.47)]
    out = _attribute_generic_text(
        _DEADLINE, _searcher({"finale Abgabe": hits}), {1: 1, 3: 2},
        context_chunks=_COURSE + [dict(h) for h in hits],
        seen_pages_by_source={1: {41}, 3: {4}}, max_distance=0.6)
    assert "[1, 08:58]" in out    # the recording, closest
    assert "[2, S. 4]" not in out  # the slide is clearly farther away
    assert out.count("[") == 1


def test_multi_chip_same_source_near_miss_still_dropped():
    # Inside one source a near miss stays out.
    hits = [_hit(1, 41, _TALK_0858, 0.31, start=538.0),
            _hit(1, 12, "irgendwann reden wir über die Abgabe", 0.47, start=180.0)]
    out = _attribute_generic_text(
        _DEADLINE, _searcher({"finale Abgabe": hits}), {1: 1},
        context_chunks=_COURSE + [dict(h) for h in hits],
        seen_pages_by_source={1: {41, 12}}, max_distance=0.6)
    assert "[1, 08:58]" in out
    assert out.count("[1,") == 1


def test_ungrounded_answer_borderline_gets_no_chip():
    # An unsupported answer gets no chip.
    line = "Diese Information ist nicht in den bereitgestellten Materialien enthalten."
    search = _searcher({"Information": [_hit(1, 5, "x", 0.7)]})
    out = _attribute_generic_text(line, search, {1: 1},
                                  seen_pages_by_source={1: {5}}, max_distance=0.6)
    assert out == line


# A course corpus where the lecturer's name occurs only in the greeting.
_GRUSS = "Dabei unterstütze ich Sie sehr gerne! Viele Grüße und einen guten Start Jürgen Klein"
_KURS = [{"content": f"Kapitel {n}: Grundlagen der Gründung und der Finanzierung im Modul."}
         for n in ("eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht",
                   "neun", "zehn")] + [{"content": _GRUSS}]


def test_short_answer_naming_the_spot_verbatim_gets_its_chip():
    # Measured on prod: a one-line answer sits at 0.629 from the only spot with the name.
    line = "Der Professor heißt **Jürgen Klein**."
    search = _searcher({"Klein": [_hit(1, 1, _GRUSS, 0.629)]})
    out = _attribute_generic_text(line, search, {1: 1}, context_chunks=_KURS,
                                  seen_pages_by_source={1: {1}}, max_distance=0.6)
    assert "[1, S. 1]" in out


def test_short_answer_without_verbatim_words_stays_without_chip():
    # Same distance, but the spot names nothing of the line, so the gate holds.
    line = "Der Professor heißt **Jürgen Klein**."
    search = _searcher({"Klein": [_hit(1, 1, _KURS[0]["content"], 0.629)]})
    out = _attribute_generic_text(line, search, {1: 1}, context_chunks=_KURS,
                                  seen_pages_by_source={1: {1}}, max_distance=0.6)
    assert out == line


# A refusal line never gets the loose chip.

# Compound question: one part answered, one part refused.
_ANSWERED = "- Die Würde des Menschen ist unantastbar laut Grundgesetz Artikel 1 Absatz 1."
_REFUSAL = "- Informationen darüber sind nicht in den bereitgestellten Materialien enthalten."
_COMPOUND = f"{_ANSWERED}\n{_REFUSAL}"


def _compound_search():
    # The refusal sits exactly in the band where the loose chip would apply.
    return _searcher({
        "Würde des Menschen": [_hit(1, 1, "Art 1 Würde des Menschen unantastbar", 0.3)],
        "Informationen darüber": [_hit(1, 44, "Kündigung am Rande erwähnt", 0.7)],
    })


def test_compound_refusal_would_be_chipped_without_detection():
    # Without the filter the refusal would get a chip on a page that backs nothing.
    out = _attribute_generic_text(_COMPOUND, _compound_search(), {1: 1},
                                  seen_pages_by_source={1: {1, 44}}, max_distance=0.6)
    assert "S. 44" in out


def test_compound_refusal_no_chip_with_detection():
    # The fix: mark the refusal line -> it gets NO chip, while the answered part keeps S. 1.
    out = _attribute_generic_text(_COMPOUND, _compound_search(), {1: 1},
                                  seen_pages_by_source={1: {1, 44}}, max_distance=0.6,
                                  refusal_lines={_REFUSAL})
    lines = out.split("\n")
    assert "[1, S. 1]" in lines[0]          # answered part keeps its source
    assert "S. 44" not in out               # refusal sentence is never sourced
    assert lines[1] == _REFUSAL             # refusal line left verbatim


def test_refusal_line_does_not_block_real_borderline_guarantee():
    # Only the line marked as a refusal loses its chip.
    text = ("- Erste klar belegte Aussage zum Thema hier.\n"
            "- Zweite Aussage etwas vager formuliert hier.")
    search = _searcher({
        "klar belegte": [_hit(1, 5, "x", 0.2)],
        "vager formuliert": [_hit(1, 8, "y", 0.7)],
    })
    out = _attribute_generic_text(text, search, {1: 1}, seen_pages_by_source={1: {5, 8}},
                                  max_distance=0.6, refusal_lines={_REFUSAL})  # unrelated flag
    assert "[1, S. 5]" in out and "[1, S. 8]" in out   # borderline real claim still guaranteed


# ── _refusal_lines (embedding-proximity to the no-info sentinel) ─────────────

def test_refusal_lines_flags_line_near_sentinel():
    sentinels = [[1.0, 0.0, 0.0]]
    cands = ["near sentinel line", "orthogonal content line"]
    vbl = {"near sentinel line": [0.99, 0.02, 0.0],
           "orthogonal content line": [0.0, 1.0, 0.0]}
    flagged = _refusal_lines(cands, vbl, sentinels, max_dist=0.40)
    assert "near sentinel line" in flagged
    assert "orthogonal content line" not in flagged


def test_refusal_lines_empty_without_sentinels():
    # Embed batch failed (no sentinel vectors) -> filter off, behaviour unchanged.
    assert _refusal_lines(["x"], {"x": [1.0, 0.0]}, [], max_dist=0.40) == set()


def test_refusal_lines_skips_lines_without_vectors():
    assert _refusal_lines(["x"], {}, [[1.0, 0.0]], max_dist=0.40) == set()


def test_cos_dist_degenerate_vector_is_max():
    # A zero vector never falsely reads as "near" a sentinel.
    assert _cos_dist([0.0, 0.0], [1.0, 0.0]) == 1.0


# The single page anchor has to recognise a refusal too.

def _fake_embed(mapping, fallback):
    # Returns the mapped vector per text (sentinels + the answer), else a fallback vector.
    return lambda texts: [mapping.get(t, fallback) for t in texts]


def test_refusal_answer_near_sentinel_is_flagged():
    sentinel = "Diese Information ist nicht in den bereitgestellten Materialien enthalten."
    answer = sentinel  # the model emits the sentinel verbatim
    embed = _fake_embed({sentinel: [1.0, 0.0, 0.0]}, fallback=[1.0, 0.0, 0.0])
    assert is_refusal_answer(answer, embed, [sentinel], max_dist=0.40) is True


def test_real_answer_far_from_sentinel_keeps_anchor():
    sentinel = "Diese Information ist nicht in den bereitgestellten Materialien enthalten."
    answer = "Ab dem dritten Juli gilt die neue Prüfungsordnung mit verkürzten Fristen."
    embed = _fake_embed({sentinel: [1.0, 0.0, 0.0], answer: [0.0, 1.0, 0.0]},
                        fallback=[0.0, 1.0, 0.0])
    assert is_refusal_answer(answer, embed, [sentinel], max_dist=0.40) is False


def test_refusal_answer_no_sentinels_is_false():
    # Embed batch failed upstream / no sentinels -> never strip the anchor.
    assert is_refusal_answer("anything", lambda t: [[1.0]], [], max_dist=0.40) is False


def test_refusal_answer_embed_failure_is_false():
    def _boom(texts):
        raise RuntimeError("embed down")
    assert is_refusal_answer("x", _boom, ["s"], max_dist=0.40) is False


def test_refusal_answer_empty_text_is_false():
    assert is_refusal_answer("   ", lambda t: [[1.0]], ["s"], max_dist=0.40) is False


# A pure refusal must not cost a whole embedding round first.

_DE = RAG_NO_INFO_SENTINEL["de"]


def test_sentinel_refusal_de_verbatim():
    assert is_sentinel_refusal(_DE) is True


def test_sentinel_refusal_tolerates_whitespace_and_emphasis():
    assert is_sentinel_refusal(f"  **{_DE}**\n\n") is True
    assert is_sentinel_refusal(_DE.rstrip(".")) is True


def test_sentinel_refusal_compound_answer_is_false():
    # The answered part keeps its chip.
    text = f"Die Frist endet am dritten Juli laut der Ordnung.\n{_DE}"
    assert is_sentinel_refusal(text) is False


def test_sentinel_refusal_real_answer_is_false():
    assert is_sentinel_refusal("Ab dem dritten Juli gilt die neue Ordnung.") is False


def test_sentinel_refusal_other_language_is_false():
    # French refusal: no literal match, so it falls through to the embedding-based net.
    assert is_sentinel_refusal("Cette information ne figure pas dans les sources.") is False


def test_sentinel_refusal_empty_is_false():
    assert is_sentinel_refusal("   ") is False
    assert is_sentinel_refusal(None) is False


def test_long_dash_delimiter_row_never_cited():
    # A table separator row has to stay verbatim, otherwise the table falls apart.
    table = (
        "| Inhalt | Termin |\n"
        "|--------|--------|\n"
        "| Webkonferenz | 25.03.2026 |"
    )
    out = _attribute_generic_text(
        table,
        _searcher({"Inhalt": [_hit(1, 2, "x", 0.2)],
                   "Webkonferenz": [_hit(1, 2, "x", 0.2)],
                   "--------": [_hit(1, 2, "x", 0.2)]}),
        {1: 1}, seen_pages_by_source={1: {2}}, max_distance=0.6,
    )
    lines = out.split("\n")
    assert lines[1] == "|--------|--------|"   # delimiter untouched -> table still parses


# ── overview mode: no loose guarantee chip, no chip on multi-law synthesis ────

def test_names_many_laws_detects_enumeration():
    assert _names_many_laws("Form (ZPO), Marken (MarkenG) und Anwalt (BRAO).") is True
    # section-style + comma-list parens count too
    assert _names_many_laws("Doku (z. B. § 21 StBerG), Behörden (§ 55 GwG), (UWG, UmwG)") is True
    assert _names_many_laws("nur das (MarkenG) wird genannt") is False
    assert _names_many_laws("zwei (ZPO) und (InsO) reichen nicht") is False
    # a descriptive Title-case paren is NOT a law list -> single-law line keeps its chip
    assert _names_many_laws("Das Markengesetz (MarkenG) schützt Zeichen (Wortmarken, Bildmarken).") is False


def test_enum_chip_unbacked_content_gated():
    # >= 4 spelled-out items, cited chunk backs only one (Bauwirtschaft) -> unbacked.
    items = "In den Ausbildungsordnungen für Maler, Flugtechnik, Heimarbeiter, Bauwirtschaft …"
    assert _enum_chip_unbacked(items, "Bauwirtschaft Dämmungen Trockenbau Prüfung") is True
    # same shape, but the cited chunk literally enumerates all items -> in-source list, keep.
    assert _enum_chip_unbacked(items, "Maler Flugtechnik Heimarbeiter Bauwirtschaft Liste") is False
    # in-source example list (the real false-positive case) -> backed, keep the chip.
    health = "In den Gesundheitsdienstberufen (Ärzte, Zahnärzte, Tierärzte, Apotheker) ist …"
    assert _enum_chip_unbacked(health, "zuständig: Ärzte, Zahnärzte, Tierärzte, Apotheker, Kammern") is False
    # only 3 items -> below the bar, never an enumeration suppression
    assert _enum_chip_unbacked("Themen: Mathematik, Physik, Chemie.", "nichts davon") is False
    # no tight comma-run at all
    assert _enum_chip_unbacked("Anforderungen an Prüfungen, Berichte und Gewichtung.", "x") is False


def test_overview_drops_enum_chip_when_chunk_backs_one_item():
    line = "- In den Ausbildungsordnungen für Maler, Flugtechnik, Heimarbeiter, Bauwirtschaft gelten Regeln."
    search = _searcher({"Ausbildungsordnungen": [_hit(1, 36, "Bauwirtschaft Dämmungen Trockenbau", 0.2)]})
    # SPECIFIC still cites it; overview drops the chip because S.36 backs only "Bauwirtschaft".
    assert "[1, S. 36]" in _attribute_generic_text(line, search, {1: 1}, max_distance=0.6)
    assert _attribute_generic_text(line, search, {1: 1}, max_distance=0.6, overview=True) == line


def test_overview_keeps_enum_chip_when_chunk_backs_all_items():
    # In-source example list: the cited chunk enumerates all four professions -> chip stays.
    line = "- In den Gesundheitsdienstberufen Ärzte, Zahnärzte, Tierärzte, Apotheker sind Kammern zuständig."
    search = _searcher({"Gesundheitsdienstberufen": [
        _hit(2, 40, "zuständige Stellen Ärzte Zahnärzte Tierärzte Apotheker Kammern", 0.2)]})
    out = _attribute_generic_text(line, search, {2: 2}, max_distance=0.6, overview=True)
    assert "[2, S. 40]" in out


def test_overview_drops_loose_guarantee_chip():
    # In the loose band the specific question gets a chip, the overview does not.
    text = ("- Klar belegte Kernaussage zum Thema steht hier drin.\n"
            "- Eine weitere eher lose verbundene Aussage zum Sachverhalt.")
    search = _searcher({
        "Kernaussage": [_hit(1, 5, "Kernaussage Thema", 0.2)],
        "lose verbundene": [_hit(2, 8, "lose", 0.72)],
    })
    out_spec = _attribute_generic_text(text, search, {1: 1, 2: 2}, max_distance=0.6)
    assert "[2, S. 8]" in out_spec                       # guarantee chip in SPECIFIC
    out_ov = _attribute_generic_text(text, search, {1: 1, 2: 2}, max_distance=0.6, overview=True)
    assert "[2, S. 8]" not in out_ov                     # dropped in overview
    assert "[1, S. 5]" in out_ov                         # the close line still cited


def test_overview_skips_multi_law_enumeration_line():
    line = "- Regelungen zur Form von Urteilen (ZPO), zu Marken (MarkenG) und zur Anwaltschaft (BRAO)."
    search = _searcher({"Regelungen": [_hit(1, 98, "Regelungen Form Urteilen", 0.2)]})
    assert "[1, S. 98]" in _attribute_generic_text(line, search, {1: 1}, max_distance=0.6)
    assert _attribute_generic_text(line, search, {1: 1}, max_distance=0.6, overview=True) == line


def test_overview_keeps_close_single_source_chip():
    line = "- Das Markengesetz schützt eingetragene Zeichen als eine Marke."
    search = _searcher({"Markengesetz": [_hit(3, 8, "Markengesetz Zeichen Marke", 0.2)]})
    out = _attribute_generic_text(line, search, {3: 3}, max_distance=0.6, overview=True)
    assert "[3, S. 8]" in out


# Chips are not deduplicated across blocks.

def test_distinct_blocks_each_keep_shared_best_source_pdf():
    # Two claims may keep the same best page.
    b1 = "- Das wissenschaftliche Seminar vermittelt die theoretischen Grundlagen hier."
    b2 = "- Im wissenschaftlichen Projekt steht die praktische Umsetzung im Vordergrund hier."
    text = b1 + "\n\n" + b2
    search = _searcher({
        "Seminar": [_hit(1, 4, "Seminar Theorie Grundlagen", 0.20),
                    _hit(1, 5, "Einblick Wissenschaft", 0.30)],
        "Projekt": [_hit(1, 4, "Seminar Projekt Praxis Umsetzung", 0.22),
                    _hit(1, 9, "ganz anderes Thema", 0.50)],
    })
    out = _attribute_generic_text(text, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source=None)
    first, second = out.split("\n\n")
    assert "[1, S. 4]" in first       # bullet 1 keeps the shared best source
    assert "[1, S. 4]" in second      # bullet 2 ALSO keeps it (was lost to dedup before)


def test_distinct_blocks_each_keep_shared_best_media():
    # For media too every block keeps its own best timestamp.
    b1 = "- Das wissenschaftliche Seminar vermittelt die theoretischen Grundlagen hier."
    b2 = "- Im wissenschaftlichen Projekt steht die praktische Umsetzung im Vordergrund hier."
    text = b1 + "\n\n" + b2
    search = _searcher({
        "Seminar": [_hit(1, 12, "Seminar Theorie", 0.20, start=227.0),     # 03:47
                    _hit(1, 14, "Einblick", 0.30, start=245.0)],            # 04:05
        "Projekt": [_hit(1, 12, "Seminar Projekt Praxis", 0.22, start=227.0),  # 03:47 best
                    _hit(1, 80, "ganz anderes Thema", 0.50, start=1564.0)],     # 26:04 leftover
    })
    out = _attribute_generic_text(text, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source=None)
    first, second = out.split("\n\n")
    assert "[1, 03:47]" in first
    assert "[1, 03:47]" in second     # was missing (only 26:04 showed) before the fix


def test_normal_mode_keeps_per_block_chips_no_cross_dedup():
    # The same chip may repeat when it backs two claims.
    line1 = "Die Abgabe der Hausarbeit ist am 03.07.2026 faellig und steht hier."
    line2 = "Der Abgabetermin der Hausarbeit ist der 03.07.2026 wie hier erneut steht."
    text = line1 + "\n\n" + line2
    search = _searcher({"Hausarbeit": [_hit(1, 6, "Abgabe 03.07.2026", 0.20)]})
    out = _attribute_generic_text(text, search, {1: 1}, max_distance=0.6)
    assert out.count("[1, S. 6]") == 2  # per-block, not deduped across the message


# Every fact of a multi-part line gets its own citation.

def test_clause_coverage_multi_fact_line_media():
    # The second clause brings back the spot the whole line lost.
    line = ("- Die Pruefungsleistung umfasst sechs bis sieben Seiten, "
            "sowie eine zwanzig Minuten Praesentation mit anschliessendem Fragegespraech.")
    search = _searcher({
        "Seiten": [_hit(1, 90, "sechs bis sieben Seiten Literaturverzeichnis", 0.20, start=893.0)],   # 14:53
        "zwanzig Minuten": [_hit(1, 93, "zwanzig Minuten Praesentation Fragekontext", 0.25, start=931.0)],  # 15:31
    })
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6, seen_pages_by_source=None)
    assert "[1, 14:53]" in out   # fact 1 (Seiten) cited as before
    assert "[1, 15:31]" in out   # fact 2 (20-min presentation) now ALSO cited (was missing)


def test_clause_coverage_multi_fact_line_pdf():
    # Same, PDF pages: each clause grounds its own page.
    line = ("- Die Pruefungsleistung umfasst sechs bis sieben Seiten, "
            "sowie eine muendliche Praesentation mit anschliessendem Fragegespraech.")
    search = _searcher({
        "Seiten": [_hit(1, 7, "sechs bis sieben Seiten", 0.20)],
        "muendliche Praesentation": [_hit(1, 12, "muendliche Praesentation Fragekontext", 0.25)],
    })
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {7, 12}})
    assert "[1, S. 7]" in out
    assert "[1, S. 12]" in out


def test_clause_coverage_drops_a_passage_that_adds_nothing_to_the_line():
    # A coverage chip has to cover something new in the line.
    line = "Die Arbeit umfasst sechs Seiten, inklusive Abbildungen und Tabellen."
    search = _searcher({
        "sechs Seiten": [_hit(1, 7, "Arbeit umfasst sechs Seiten Abbildungen Tabellen", 0.20)],
        "inklusive Abbildungen": [_hit(1, 30, "Vorlesungsplan Termine Raeume Anmeldung", 0.30)],
    })
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {7, 30}})
    assert "[1, S. 7]" in out
    assert "[1, S. 30]" not in out   # covers nothing of the line -> no chip


def test_clause_coverage_keeps_a_second_DOCUMENT_even_for_the_same_fact():
    # A second source is a second way in and stays.
    line = ("Das Seminar und das Projekt bauen aufeinander auf, "
            "beide bereiten auf die spaetere Masterarbeit vor.")
    slide = _hit(1, 2, "Seminar und Projekt bauen aufeinander auf Vorbereitung Masterarbeit", 0.20)
    # SAME statement, other file: the recording of that slide.
    talk = {"source_id": 2, "page_number": None,
            "content": "Seminar und Projekt bauen aufeinander auf Vorbereitung Masterarbeit",
            "vec_distance": 0.24, "start_time": 245.0}
    search = _searcher({"Das Seminar und das Projekt": [slide],
                        "beide bereiten auf die spaetere": [talk]})
    out = _attribute_generic_text(line, search, {1: 1, 2: 2}, max_distance=0.6,
                                  seen_pages_by_source={1: {2}, 2: set()})
    assert "[1, S. 2]" in out      # the slide
    assert "[2, 04:05]" in out     # the recording of the same fact stays


def test_clause_coverage_keeps_a_passage_that_covers_a_new_fact():
    # The case coverage exists for still holds.
    line = "Die Pruefung umfasst sechs Seiten, sowie eine muendliche Praesentation dazu."
    search = _searcher({
        "sechs Seiten": [_hit(1, 7, "Pruefung umfasst sechs Seiten Umfang", 0.20)],
        "muendliche Praesentation": [_hit(1, 12, "muendliche Praesentation Fragekontext Dauer", 0.25)],
    })
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {7, 12}})
    assert "[1, S. 7]" in out
    assert "[1, S. 12]" in out       # covers "muendliche Praesentation" -> earns its chip


def test_clause_coverage_no_inflation_when_clauses_share_source():
    # Both clauses ground in the SAME page -> still ONE chip (dedup by target), no inflation.
    line = "Die Regel betrifft die Anmeldung, sowie auch die Abmeldung im selben Abschnitt."
    search = _searcher({"Anmeldung": [_hit(1, 5, "Anmeldung Abmeldung Abschnitt", 0.20)],
                        "Abmeldung": [_hit(1, 5, "Anmeldung Abmeldung Abschnitt", 0.22)]})
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {5}})
    assert out.count("[1, S. 5]") == 1


# The line names two numbers that only the slide carries.
_TALK_0928 = ("werden Sie auch gesehen haben, dass da auch eine Präsentation dabei ist. "
              "Sie haben einen schriftlichen Teil und dann präsentieren Sie Ihre "
              "Ausarbeitung, sage ich mal, oder die Ergebnisse, was Sie da recherchiert "
              "haben. Und die Termine werden wir dann individuell vereinbaren. Die werden "
              "dann während der Prüfungswochen sein.")
_SLIDE_TIMES = ("ORGANISATORISCHES PRÜFUNGSLEISTUNG Die finale Hausarbeit soll ca. sechs "
                "bis sieben Seiten betragen, inklusive Abbildungen und Tabellen, "
                "zuzüglich Literaturverzeichnis. 20 Minuten Präsentation + 10 Minuten "
                "anschließende Fragerunde")
# A corpus where every long word of the line appears everywhere.
_SEMINAR = [{"content": ("Hinweise zur Präsentation, zur Fragerunde, zum schriftlichen "
                         "Teil und zu individuell vereinbarten Terminen in den "
                         f"Prüfungswochen, Abschnitt {n}.")}
            for n in "abcdefghijklmnop"] + [
    {"content": "Zusätzlich gilt die Anwesenheitspflicht in allen Sitzungen."}]


def test_clause_coverage_keeps_the_page_that_states_the_lines_figures():
    # Reported: the slide names the duration, the only chip pointed at the recording.
    line = ("Zusätzlich zur schriftlichen Arbeit erfolgt eine 20-minütige Präsentation "
            "mit einer anschließenden 10-minütigen Fragerunde, wobei die Termine "
            "individuell während der Prüfungswochen vereinbart werden.")
    talk = _hit(1, 22, _TALK_0928, 0.28, start=568.0)
    slide = _hit(3, 7, _SLIDE_TIMES, 0.42)
    out = _attribute_generic_text(
        line, _searcher({"Prüfungswochen vereinbart": [talk],
                         "10-minütigen Fragerunde": [slide]}), {1: 1, 3: 2},
        context_chunks=_SEMINAR + [dict(talk), dict(slide)],
        seen_pages_by_source={1: {22}, 3: {7}}, max_distance=0.6)
    assert "[1, 09:28]" in out   # the recording, it states the dates
    assert "[2, S. 7]" in out    # the slide, it states the 20 and the 10


def test_clause_coverage_states_the_figures_in_a_bullet_too():
    # The same sentence as a bullet, that is how it arrived in the reported case.
    line = ("- **Präsentation**: Zusätzlich zur schriftlichen Arbeit erfolgt eine "
            "20-minütige Präsentation mit einer anschließenden 10-minütigen Fragerunde, "
            "wobei die Termine individuell während der Prüfungswochen vereinbart werden.")
    talk = _hit(1, 22, _TALK_0928, 0.28, start=568.0)
    slide = _hit(3, 7, _SLIDE_TIMES, 0.42)
    out = _attribute_generic_text(
        line, _searcher({"Prüfungswochen vereinbart": [talk],
                         "10-minütigen Fragerunde": [slide]}), {1: 1, 3: 2},
        context_chunks=_SEMINAR + [dict(talk), dict(slide)],
        seen_pages_by_source={1: {22}, 3: {7}}, max_distance=0.6)
    assert "[1, 09:28]" in out
    assert "[2, S. 7]" in out


def test_clause_coverage_picks_the_figure_passage_over_a_nearer_stranger():
    # Reported: the extra citation landed on an aside from a different source.
    line = ("- **Präsentation**: Die schriftliche Ausarbeitung wird in einer 20-minütigen "
            "Präsentation vorgestellt, auf die eine 10-minütige Fragerunde folgt.")
    talk = _hit(1, 45, "es sind 20 Minuten Präsentation und anschließend geht man in einen "
                       "Fragekontext", 0.25, start=931.0)
    # Closer, but only talks around the matter, and from a third file.
    fremd = _hit(4, 2, "Dann gibt es natürlich immer die Möglichkeit Fragen zu stellen, "
                       "Diskussionen zu machen, je nachdem wie schnell wir durchkommen",
                 0.30, start=43.9)
    folie = _hit(3, 3, "ORGANISATORISCHES PRÜFUNGSLEISTUNG Präsentationsvorgaben "
                       "20 Minuten PPT-Präsentation 10 Minuten Fragerunde/Diskussion", 0.44)
    out = _attribute_generic_text(
        line, _searcher({"schriftliche Ausarbeitung": [talk],
                         "10-minütige Fragerunde": [fremd, folie]}), {1: 1, 3: 2, 4: 3},
        context_chunks=_SEMINAR + [dict(talk), dict(fremd), dict(folie)],
        seen_pages_by_source={1: {45}, 3: {3}, 4: {2}}, max_distance=0.6)
    assert "[2, S. 3]" in out      # the slide, it names the 20 and the 10
    assert "[3, 00:43]" not in out  # not the chatter about questions during the lecture


def test_coverage_chips_never_exceed_the_cap():
    # The limit was only checked after appending, which let a fourth chip in.
    line = ("- **Präsentation**: Die Ausarbeitung wird in einer 20-minütigen Präsentation "
            "vorgestellt, auf die eine 10-minütige Fragerunde folgt.")
    nah = [_hit(1, 45, "20 Minuten Präsentation und ein Fragekontext danach", 0.25, start=931.0),
           _hit(3, 3, "20 Minuten PPT-Präsentation 10 Minuten Fragerunde/Diskussion", 0.26),
           _hit(2, 7, "20 Minuten Präsentation + 10 Minuten anschließende Fragerunde", 0.27)]
    fremd = _hit(4, 2, "die Möglichkeit Fragen zu stellen, Diskussionen zu machen", 0.30, start=43.9)
    out = _attribute_generic_text(
        line, _searcher({"Die Ausarbeitung wird": nah,
                         "10-minütige Fragerunde": [fremd]}), {1: 1, 2: 2, 3: 3, 4: 4},
        context_chunks=_SEMINAR + [dict(h) for h in nah + [fremd]],
        seen_pages_by_source={1: {45}, 2: {7}, 3: {3}, 4: {2}}, max_distance=0.6)
    assert out.count("[") == 3        # never more than the cap
    assert "[4, 00:43]" not in out    # the fourth is dropped, the weakest one


# A prose paragraph gets a chip after every sentence.

def test_prose_paragraph_chips_each_sentence():
    line = ("Der Kurs vermittelt die Grundlagen des wissenschaftlichen Arbeitens. "
            "Die Abgabe der Hausarbeit ist am 03.07.2026 faellig.")
    search = _searcher({
        "Grundlagen des wissenschaftlichen": [_hit(1, 4, "Grundlagen wissenschaftliches Arbeiten Methoden", 0.2)],
        "Abgabe der Hausarbeit": [_hit(1, 8, "Abgabe Hausarbeit Termin 03.07.2026", 0.2)],
    })
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {4, 8}})
    assert "Arbeitens [1, S. 4]." in out           # chip right after sentence 1
    assert "faellig [1, S. 8]." in out             # chip right after sentence 2
    assert out.count("[1, S. 4]") == 1
    assert out.count("[1, S. 8]") == 1


def test_prose_sentence_chips_capped_at_three():
    # The ceiling applies per sentence, matching the display in the browser.
    line = ("Der Kurs behandelt die Grundlagen, die Abgabe der Hausarbeit, "
            "das Kolloquium im Folgesemester, sowie die Anmeldung im Pruefungsamt.")
    search = _searcher({
        "Grundlagen": [_hit(1, 4, "Grundlagen wissenschaftliches Arbeiten", 0.2)],
        "Abgabe der Hausarbeit": [_hit(1, 8, "Abgabe Hausarbeit Termin", 0.2)],
        "Kolloquium": [_hit(1, 12, "Kolloquium Folgesemester", 0.2)],
        "Anmeldung im Pruefungsamt": [_hit(1, 16, "Anmeldung Pruefungsamt Frist", 0.2)],
    })
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {4, 8, 12, 16}})
    assert out.count("[1, S.") == 3
    assert "[1, S. 16]" not in out                  # the fourth source is dropped, not shown


# One suppression must not silence the whole block.

def test_bullet_keeps_chip_despite_one_abbreviation_list_sentence():
    # Boolean operators in brackets read like statute abbreviations.
    line = ("- Fuer die Literaturrecherche sollst du verschiedene Strategien nutzen. "
            "Du kannst ein Schneeballsystem verwenden, indem du Literaturverzeichnisse durchsuchst. "
            "Du sollst Boolesche Operationen (AND, OR, NOT) und Phrasensuche verwenden. "
            "Du sollst Notizen machen und ein System fuer den Umgang mit Literatur aufbauen.")
    search = _searcher({"Literaturrecherche": [_hit(1, 9, "Literaturrecherche Strategien Schneeballsystem", 0.24)]})
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6, overview=True,
                                  seen_pages_by_source={1: {9}})
    assert "[1, S. 9]" in out


def test_bullet_keeps_chip_despite_one_example_list_sentence():
    # Live case: conference content whose third sentence lists session formats.
    line = ("- Du lernst, wie wissenschaftliche Tagungen organisiert sind und ablaufen. "
            "Die Ausrichter sind meist Hochschulen und Fachverbaende aus dem Fachgebiet. "
            "Es gibt verschiedene Formate: Vortraege, Poster, Workshops, Tutorien, Demos. "
            "Die angenommenen Beitraege werden im Tagungsband veroeffentlicht.")
    search = _searcher({"Tagungen": [_hit(1, 15, "Tagungen Ausrichter Hochschulen Fachverbaende Tagungsband", 0.3)]})
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6, overview=True,
                                  seen_pages_by_source={1: {15}})
    assert "[1, S. 15]" in out


def test_single_line_enumeration_is_still_suppressed():
    # A line of nothing but statute abbreviations still stays chip free.
    line = "Die Regelungen stehen im (ZPO), im (MarkenG) und in (§ 21 StBerG) nebeneinander."
    search = _searcher({"Regelungen": [_hit(1, 5, "eine Seite ueber die ZPO allein", 0.2)]})
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6, overview=True,
                                  seen_pages_by_source={1: {5}})
    assert out == line


def test_bullet_with_only_enumerating_sentences_stays_suppressed():
    # If it hits every sentence, the whole block stays chip free.
    line = ("- Die Regelungen stehen im (ZPO), im (MarkenG) und in (§ 21 StBerG) nebeneinander. "
            "Ergaenzend gelten die Vorgaben aus (UWG), (UmwG) und (BauGB) fuer diesen Bereich.")
    search = _searcher({"Regelungen": [_hit(1, 5, "eine Seite ueber die ZPO allein", 0.2)]})
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6, overview=True,
                                  seen_pages_by_source={1: {5}})
    assert out == line


def test_prose_unsupported_sentence_gets_no_chip():
    line = ("Die Abgabe der Hausarbeit ist am 03.07.2026 faellig. "
            "Dieser vage Zusatz steht so nicht in den Quellen.")
    search = _searcher({
        "Abgabe der Hausarbeit": [_hit(1, 8, "Abgabe Hausarbeit 03.07.2026", 0.2)],
        "vage Zusatz": [_hit(1, 5, "irrelevant weit weg", 0.9)],   # beyond the gate
    })
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {5, 8}})
    assert "faellig [1, S. 8]." in out              # supported sentence keeps its own chip
    assert "[1, S. 5]" not in out                   # unsupported sentence stays chip-less


def test_bullet_two_sentences_not_chipped_per_sentence():
    # A bullet keeps its block behaviour, no chip in the middle.
    line = "- Der Kurs vermittelt die Grundlagen. Die Abgabe ist im Juli faellig."
    search = _searcher({"Grundlagen": [_hit(1, 4, "Grundlagen wissenschaftliches Arbeiten", 0.2)]})
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {4}})
    assert "Grundlagen. [1" not in out              # no chip mid-bullet (not per-sentence)
    assert "Grundlagen [1" not in out               # nor before the first sentence's period
    assert out.rstrip().endswith("faellig [1, S. 4].")  # one chip at the end, before the period


def test_prose_single_sentence_chip_at_end_unchanged():
    # One-sentence prose is unchanged: a single chip at the end (routes through the block path).
    line = "Die Abgabe der Hausarbeit ist am 03.07.2026 faellig und steht so hier."
    search = _searcher({"Abgabe der Hausarbeit": [_hit(1, 8, "Abgabe Hausarbeit 03.07.2026", 0.2)]})
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {8}})
    assert out == f"{line[:-1]} [1, S. 8]."


def test_chip_goes_before_the_sentence_period():
    # The source chip sits BEFORE the sentence-ending period, not after it.
    line = "Die Abgabe der Hausarbeit ist am 03.07.2026 faellig und steht so hier."
    search = _searcher({"Abgabe der Hausarbeit": [_hit(1, 8, "Abgabe Hausarbeit 03.07.2026", 0.2)]})
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {8}})
    assert out.endswith("[1, S. 8].")          # chip THEN period
    assert ". [1, S. 8]" not in out            # never period-then-chip


def test_bullet_chip_also_before_period():
    # A bullet ending in a period gets the same order: chip before the period.
    line = "- Der Kurs vermittelt die wissenschaftlichen Grundlagen im Seminar."
    search = _searcher({"wissenschaftlichen Grundlagen": [_hit(1, 4, "Grundlagen wissenschaftliches Arbeiten", 0.2)]})
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {4}})
    assert out.endswith("[1, S. 4].")
    assert ". [1, S. 4]" not in out


def test_bullet_ending_in_bold_appends_chip_no_reorder():
    # The chip must not end up inside the bold markup.
    line = "- **Wörtliches Zitat vom Autor.**"
    search = _searcher({"Wörtliches Zitat": [_hit(1, 3, "Woertliches Zitat Autor Jahr Seite", 0.2)]})
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {3}})
    assert out == "- **Wörtliches Zitat vom Autor.** [1, S. 3]"


def test_bold_leadin_stays_chip_free_and_prose_below_chips_per_sentence():
    # A bold intro line stays chip free and does not swallow the paragraph.
    text = ("**Überblick**\n"
            "Der Kurs vermittelt die Grundlagen des wissenschaftlichen Arbeitens. "
            "Die Abgabe der Hausarbeit ist am 03.07.2026 faellig.")
    search = _searcher({
        "Grundlagen des wissenschaftlichen": [_hit(1, 4, "Grundlagen wissenschaftliches Arbeiten Methoden", 0.2)],
        "Abgabe der Hausarbeit": [_hit(1, 8, "Abgabe Hausarbeit Termin 03.07.2026", 0.2)],
    })
    out = _attribute_generic_text(text, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {4, 8}})
    lines = out.split("\n")
    assert lines[0] == "**Überblick**"            # bold lead-in stays chip-free
    assert "Arbeitens [1, S. 4]." in lines[1]     # sentence 1 keeps its own chip
    assert lines[1].rstrip().endswith("faellig [1, S. 8].")


# A heading claims nothing and never gets a chip.

def test_markdown_heading_line_is_never_cited():
    # Observed live: a chip glued to a section title.
    line = "### Tipps fuer die Literatursuche im Studium"
    search = _searcher({"Literatursuche": [_hit(1, 9, "Literatursuche Stichwoerter Tipps", 0.2)]})
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {9}})
    assert out == line


def test_markdown_heading_does_not_swallow_the_paragraph_below():
    text = ("### Tipps fuer die Literatursuche im Studium\n"
            "Du solltest Stichwoerter sammeln und dabei auch an Synonyme denken.")
    search = _searcher({"Stichwoerter": [_hit(1, 9, "Stichwoerter Synonyme sammeln", 0.2)]})
    out = _attribute_generic_text(text, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {9}})
    lines = out.split("\n")
    assert lines[0] == "### Tipps fuer die Literatursuche im Studium"
    assert lines[1].rstrip().endswith("denken [1, S. 9].")


def test_bold_heading_line_is_never_cited():
    line = "**Was ist eine Literaturrecherche im Studium**?"
    search = _searcher({"Literaturrecherche": [_hit(1, 4, "Literaturrecherche Quellen Thema", 0.2)]})
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {4}})
    assert out == line


def test_bold_heading_does_not_swallow_the_paragraph_below():
    # The heading starts its own block, the chip lands in the paragraph.
    text = ("**Was ist eine Literaturrecherche im Studium**?\n"
            "Literaturrecherche bedeutet, dass du nach Quellen zu deinem Thema suchst.")
    search = _searcher({"Literaturrecherche": [_hit(1, 4, "Literaturrecherche Quellen Thema", 0.2)]})
    out = _attribute_generic_text(text, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {4}})
    lines = out.split("\n")
    assert lines[0] == "**Was ist eine Literaturrecherche im Studium**?"
    assert lines[1].rstrip().endswith("suchst [1, S. 4].")


def test_partially_bold_prose_line_is_still_cited():
    # Emphasis INSIDE a sentence is not a heading — that line is a claim and keeps its chip.
    line = "Die **Literaturrecherche** ist ein fester Teil des wissenschaftlichen Seminars."
    search = _searcher({"Literaturrecherche": [_hit(1, 4, "Literaturrecherche Seminar Teil", 0.2)]})
    out = _attribute_generic_text(line, search, {1: 1}, max_distance=0.6,
                                  seen_pages_by_source={1: {4}})
    assert out.rstrip().endswith("Seminars [1, S. 4].")


# The sub-units have to be embedded in the same batch.

def test_subunits_prose_multisentence_returns_each_sentence():
    line = "Der Kurs vermittelt die Grundlagen. Die Abgabe ist im Juli faellig."
    assert _attribution_subunits(line) == [
        "Der Kurs vermittelt die Grundlagen.",
        "Die Abgabe ist im Juli faellig.",
    ]


def test_subunits_prose_sentence_with_comma_includes_its_clauses():
    line = "Der Kurs deckt Theorie, Methoden und Praxis ab. Die Abgabe folgt spaeter."
    units = _attribution_subunits(line)
    assert "Der Kurs deckt Theorie, Methoden und Praxis ab." in units   # sentence 1
    assert "Die Abgabe folgt spaeter." in units                         # sentence 2
    assert "Der Kurs deckt Theorie" in units                            # clause of sentence 1


def test_subunits_bullet_returns_clauses_not_sentences():
    # A bullet is NOT split per sentence: only its comma-clauses are extra units.
    line = "- Die Pruefung umfasst sechs Seiten, sowie eine muendliche Praesentation dazu."
    units = _attribution_subunits(line)
    assert "- Die Pruefung umfasst sechs Seiten" in units          # a comma-clause
    assert "sowie eine muendliche Praesentation dazu." in units    # the other clause
    # NOT split into sentences (it is a bullet) -> the whole bullet is never an extra unit.
    assert "- Die Pruefung umfasst sechs Seiten, sowie eine muendliche Praesentation dazu." not in units


def test_subunits_single_sentence_prose_has_no_extra_sentence_units():
    line = "Die Abgabe der Hausarbeit ist am 03.07.2026 faellig und steht so hier."
    # No comma, single sentence -> no sub-units at all.
    assert _attribution_subunits(line) == []




# ── looking a figure up, instead of only ranking by meaning ──────────────────

from src.features.ai_assistant.routes._evidence import _chips_for_line, _line_candidates

_SLIDE = ("Lenka Kleinau Kontakt: Fachforum E-Mail: lenka.kleinau@example.org "
          "Wöchentliche Sprechstunde (Mittwoch 17:30-18:30 Uhr) MENTORIN UND TUTORIN")
_LINE = ("Zusätzlich finden ab dem 22.04.2026 wöchentliche offene Sprechstunden statt "
         "(mittwochs von 17:30 bis 18:30 Uhr)")
_CORPUS = [f"Kapitel {i}: Text über wissenschaftliches Arbeiten und Publizieren." for i in range(20)]


def _talk(i, dist):
    return {"id": 100 + i, "source_id": 9, "page_number": 60 + i, "start_time": 100.0 + i,
            "content": f"Da wird es dann mittwochs eine offene Sprechstunde geben, Teil {i}. " * 3,
            "vec_distance": dist}


def test_the_passage_that_states_the_time_is_cited_although_it_ranks_last():
    # Three near misses fill every slot, the right slide would never get in.
    slide = {"id": 7, "source_id": 3, "page_number": 2, "start_time": None,
             "content": _SLIDE, "vec_distance": 0.54}
    hits = [_talk(0, 0.398), _talk(1, 0.420), _talk(2, 0.433), slide]
    lookup = lambda fig: [slide] if fig in ("17:30", "18:30", "17:30-18:30") else []
    cands = _line_candidates(_LINE, lambda _l: hits, None, None, None,
                             literal_lookup=lookup, corpus=_CORPUS)
    chips = _chips_for_line(cands, {3: 4, 9: 1}, 0.6, line=_LINE, corpus=_CORPUS)
    assert "[4, S. 2]" in chips


def test_the_closest_passage_still_leads():
    slide = {"id": 7, "source_id": 3, "page_number": 2, "start_time": None,
             "content": _SLIDE, "vec_distance": 0.54}
    hits = [_talk(0, 0.398), slide]
    lookup = lambda fig: [slide] if fig == "17:30" else []
    cands = _line_candidates(_LINE, lambda _l: hits, None, None, None,
                             literal_lookup=lookup, corpus=_CORPUS)
    assert cands[0]["id"] == 100


def test_a_rarer_literal_match_outranks_a_common_one():
    # The date stands on four pages, the time on one. The time is the better evidence.
    common = [{"id": 200 + i, "source_id": 5, "page_number": 4 + i, "start_time": None,
               "content": f"Ab dem 22.04.2026 offene Sprechstunden, Seite {i}. " * 4,
               "vec_distance": 0.46} for i in range(4)]
    slide = {"id": 7, "source_id": 3, "page_number": 2, "start_time": None,
             "content": _SLIDE, "vec_distance": 0.54}
    lookup = lambda fig: common if fig == "22.04.2026" else ([slide] if fig in ("17:30", "18:30") else [])
    cands = _line_candidates(_LINE, lambda _l: [_talk(0, 0.398)] + common + [slide],
                             None, None, None, literal_lookup=lookup, corpus=_CORPUS)
    assert cands[1]["id"] == 7


def test_without_a_lookup_nothing_changes():
    hits = [_talk(0, 0.398), _talk(1, 0.420)]
    assert _line_candidates(_LINE, lambda _l: hits, None, None, None) == sorted(
        hits, key=lambda h: h["vec_distance"])


# ── lead-in of an overview (no chip on the sentence about the whole material) ─

def test_lead_in_ohne_ueberschrift_gibt_es_nicht():
    assert _lead_in_lines(["Ein Satz.", "Noch ein Satz."]) == set()


def test_lead_in_reicht_bis_zur_ersten_abschnitts_ueberschrift():
    zeilen = ["Die Materialien umfassen vieles.", "", "## Arbeitsrecht", "Das Gesetz regelt."]
    assert _lead_in_lines(zeilen) == {0, 1}


def test_eine_titelzeile_oben_zaehlt_nicht_als_abschnitt():
    """A heading at the very top is the answer's title, not a section."""
    zeilen = ["**Überblick über die Materialien**", "Die Materialien umfassen vieles.",
              "**Gesellschaftsrecht (GmbHG)**", "Das Gesetz regelt."]
    assert _lead_in_lines(zeilen) == {0, 1}


def test_lead_in_ohne_zweite_ueberschrift_ist_leer():
    zeilen = ["## Überblick", "Die Materialien umfassen vieles."]
    assert _lead_in_lines(zeilen) == set()


_LEAD_TEXT = ("Die Materialien behandeln viele Bereiche des deutschen Rechts.\n"
              "\n"
              "## Arbeitsrecht\n"
              "\n"
              "Das Arbeitszeitgesetz regelt die tägliche Höchstarbeitszeit.")

_LEAD_SEARCH = {"Materialien": [_hit(1, 3, "Materialien und Bereiche des Rechts", 0.2)],
                "Arbeitszeitgesetz": [_hit(2, 5, "Arbeitszeitgesetz Höchstarbeitszeit", 0.2)]}


def test_einleitungssatz_eines_ueberblicks_bekommt_keinen_chip():
    out = _attribute_generic_text(_LEAD_TEXT, _searcher(_LEAD_SEARCH), {1: 1, 2: 2},
                                  max_distance=0.6, overview=True)
    zeilen = out.split("\n")
    assert zeilen[0] == "Die Materialien behandeln viele Bereiche des deutschen Rechts."
    assert zeilen[-1].endswith("[2, S. 5].")


def test_ausserhalb_des_ueberblicks_behaelt_der_erste_satz_seinen_chip():
    out = _attribute_generic_text(_LEAD_TEXT, _searcher(_LEAD_SEARCH), {1: 1, 2: 2},
                                  max_distance=0.6, overview=False)
    assert out.split("\n")[0].endswith("[1, S. 3].")
