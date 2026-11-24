"""AI assistant Celery tasks: mindmap generation."""

from langfuse.decorators import observe
from loguru import logger

from src import database as db
from src.celery_app import celery_app
from src.core.redis_url import REDIS_URL
from src.features.ai_assistant.prompts.studio_prompts import AIA_MINDMAP_PROMPT
from src.features.ai_assistant.tasks._context_budget import (
    overview_context_budget,
    tool_context_budget,
)
from src.features.ai_assistant.tasks._instruction import (
    NONE,
    Resolution,
    prompt_block,
    spots_by_source,
)
from src.features.ai_assistant.tasks._instruction import resolve as resolve_instruction
from src.features.ai_assistant.tasks._json_commas import close_brackets, drop_trailing_commas
from src.features.ai_assistant.tasks._source_tags import SourceTags
from src.features.ai_assistant.tasks.studio import _mindmap_condensed as _condensed
from src.features.ai_assistant.tasks.studio._attribution import _fmt_ts, _is_media_source
from src.limits import AIA_TOOL_SOFT_TIME_LIMIT, AIA_TOOL_TIME_LIMIT
from src.services.aia_adaptive_tools import build_adaptive_tool_suffix
from src.services.llm_call import create_logged


def _ask_json(client, model, messages: list[dict], mindmap_id: int,
              max_tokens: int | None = None, tags: SourceTags | None = None) -> dict | None:
    """One request that must answer JSON, with a second try on a broken answer."""
    import json as _json
    grenze = {"max_tokens": max_tokens} if max_tokens else {}
    if tags is not None:
        messages = tags.encode(messages)
    for attempt in range(2):
        response = create_logged(client, endpoint="mindmap", model=model,
                                 messages=messages, temperature=0.2, **grenze)
        msg = response.choices[0].message
        raw = msg.content or getattr(msg, "reasoning_content", None)
        if not raw:
            continue
        answer = raw.strip()
        if answer.startswith("```"):
            answer = answer.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        # Strip leading thinking tags if model wrapped output
        if answer.startswith("<think>"):
            think_end = answer.find("</think>")
            if think_end != -1:
                answer = answer[think_end + 8:].strip()
        try:
            # Both attempts get the same prompt and nearly the same answer, a slip has to be fixed here.
            data = _json.loads(close_brackets(drop_trailing_commas(answer)))
            return tags.decode(data) if tags is not None else data
        except _json.JSONDecodeError as e:
            logger.warning("mindmap {} JSON parse failed (attempt {}/2): {}",
                           mindmap_id, attempt + 1, e)
    return None


class _Zwischenstand:
    """The finished steps of a small model's map in Redis, so a requeued run continues there."""

    def __init__(self, mindmap_id: int):
        self._key = f"askf:mindmap-stand:{mindmap_id}"

    def _redis(self):
        import redis
        return redis.from_url(REDIS_URL,
                              socket_connect_timeout=2, socket_timeout=2)

    def get(self, feld: str, default=None):
        import json as _json
        try:
            roh = self._redis().hget(self._key, feld)
        except Exception as e:  # noqa: BLE001 - without Redis the run simply starts from the front
            logger.debug("Mindmap-Zwischenstand nicht lesbar: {}", e)
            return default
        return _json.loads(roh) if roh else default

    def __setitem__(self, feld: str, wert) -> None:
        import json as _json
        try:
            r = self._redis()
            r.hset(self._key, feld, _json.dumps(wert, ensure_ascii=False))
            r.expire(self._key, 86400)
        except Exception as e:  # noqa: BLE001
            logger.debug("Mindmap-Zwischenstand nicht speicherbar: {}", e)

    def loeschen(self) -> None:
        try:
            self._redis().delete(self._key)
        except Exception as e:  # noqa: BLE001
            logger.debug("Mindmap-Zwischenstand nicht loeschbar: {}", e)


def _collect_sources(source_ids: list[int], source_uuids: list[str]
                     ) -> list[tuple[int, str, list[dict], list[dict]]]:
    """Per source: id, label, all its chunks and the window that fits the budget."""
    from src.features.ai_assistant.tasks._context_budget import (
        fill_sources_evenly, overview_context_budget,
    )

    # The id comes from the source itself, pairing by position silently swaps file names.
    vorhanden: list[tuple[int, str, list[dict]]] = []
    for suuid in source_uuids:
        source = db.get_aia_source(suuid)
        if not source:
            continue
        chunks = db.get_chunks_by_source(source["id"])
        if chunks:
            vorhanden.append((source["id"], source["filename"], chunks))

    alle = {sid: chunks for sid, _label, chunks in vorhanden}
    return [(sid, label, alle[sid], picked)
            for sid, label, picked in fill_sources_evenly(vorhanden, overview_context_budget())]


def _source_context(gesammelt: list[tuple[int, str, list[dict], list[dict]]]
                    ) -> tuple[list[str], dict[str, list]]:
    """One labelled block per source, and per media file all its chunks for the timestamps."""
    context_parts: list[str] = []
    media_chunks_by_label: dict[str, list] = {}
    for _sid, source_label, alle_chunks, gewaehlt in gesammelt:
        if _is_media_source(source_label):
            media_chunks_by_label[source_label] = alle_chunks
            parts = []
            for c in gewaehlt:
                st = c.get("start_time")
                time_label = _fmt_ts(st) if st is not None else f"Teil {c['page_number']}"
                parts.append(f"[{source_label}, {time_label}] {c['content']}")
        else:
            parts = [f"[{source_label}, S. {c['page_number']}] {c['content']}" for c in gewaehlt]
        context_parts.append(f"--- {source_label} ---\n" + "\n".join(parts))
    return context_parts, media_chunks_by_label


def _build_stepwise(mindmap_id: int, client, model, tags: SourceTags, quellen: list[dict],
                    gesammelt: list, workspace_id, source_ids: list[int],
                    language: str, adaptive_suffix: str) -> dict | None:
    """The stepwise way of a small model: skeleton from the summaries, depth from search."""
    from src.services import model_limits
    from src.services.aia_embeddings import get_embedding_provider_with_fallback
    provider_emb = get_embedding_provider_with_fallback()
    label_of = {q["id"]: q["label"] for q in quellen}
    id_of = {q["label"]: q["id"] for q in quellen}

    def suche(frage: str, vektor, limit: int) -> list[dict]:
        """The passages for one node, each tagged with the file it stands in."""
        treffer = db.hybrid_search_chunks(
            workspace_id, frage, vektor, source_ids=source_ids, limit=limit) or []
        for c in treffer:
            c["source_label"] = label_of.get(c.get("source_id"), "")
        return treffer

    # What stands where, built from the chunks we already hold.
    stellen: dict[tuple[str, str], str] = {}
    for _sid, label, alle, _p in gesammelt:
        for c in alle:
            st = c.get("start_time")
            schluessel = (label, _fmt_ts(st) if st is not None else str(c.get("page_number")))
            stellen[schluessel] = stellen.get(schluessel, "") + " " + (c.get("content") or "")

    def im_eigenen_dokument(frage: str, label: str, limit: int) -> list[dict]:
        """Candidates for one leaf, only from the file that leaf already names."""
        sid = id_of.get(label)
        if not sid:
            return []
        treffer = db.hybrid_search_chunks(
            workspace_id, frage, provider_emb.embed_one(frage),
            source_ids=[sid], limit=limit) or []
        for c in treffer:
            c["source_label"] = label
        return treffer

    # Every call also writes, so it reads only the chat share of the window.
    return _condensed.build_small(
        sources=quellen, language=language, adaptive_suffix=adaptive_suffix,
        ask=lambda nachrichten: _ask_json(client, model, nachrichten, mindmap_id,
                                          max_tokens=model_limits.CHAT_MAX_OUTPUT_TOKENS,
                                          tags=tags),
        embed=provider_emb.embed_one, search=suche,
        limit_chars=model_limits.cap_for_window(tool_context_budget(),
                                                model_limits.CHAT_SHARE),
        stand=_Zwischenstand(mindmap_id),
        verify=lambda label, stelle: stellen.get((label, str(stelle)), ""),
        locate=im_eigenen_dokument,
    )


def _fix_media_nodes(node, media_chunks_by_label: dict[str, list]) -> None:
    """For media the guessed page number is replaced by a real timestamp."""
    if not isinstance(node, dict):
        return
    label = node.get("source_label")
    chunks = media_chunks_by_label.get(label) if label else None
    if chunks is not None:  # node cites a media source
        kw = (node.get("keyword") or "").strip().lower()
        ts = None
        if kw:
            for c in chunks:
                if c.get("start_time") is not None and kw in (c.get("content") or "").lower():
                    ts = _fmt_ts(c["start_time"])
                    break
        if ts is not None:
            node["page_number"] = ts
        else:
            node.pop("page_number", None)
    for ch in (node.get("children") or []):
        _fix_media_nodes(ch, media_chunks_by_label)


@celery_app.task(bind=True, name="aia.generate_mindmap", queue="aia",
                 soft_time_limit=AIA_TOOL_SOFT_TIME_LIMIT, time_limit=AIA_TOOL_TIME_LIMIT)
@observe(name="aia-mindmap")
def run_generate_mindmap(self, mindmap_id: int, source_ids: list[int], source_uuids: list[str],
                          locale: str = "de", _aia_job_uuid: str | None = None,
                          user_id: int | None = None, anlauf: int = 0, seit: float | None = None):
    """Generates a mind map from the sources as a background job."""
    # A requeued run takes the seat along and gives it back itself.
    platz_weiter = False
    klein = False

    from src.features.ai_assistant.tasks._helpers import learning_tools_language
    # The generated content follows the management setting.
    _, language = learning_tools_language()

    try:
        db.update_aia_mindmap(mindmap_id, "running")
        logger.info("KI Tutor: generating mindmap {}", mindmap_id)

        gesammelt = _collect_sources(source_ids, source_uuids)
        # The instruction decides whether all the material or only the found spots go in.
        zeile = db.get_aia_mindmap(mindmap_id) or {}
        gewuenscht = zeile.get("user_instruction") or ""
        wahl = (resolve_instruction(zeile.get("workspace_id"), source_ids, gewuenscht,
                                    overview_context_budget())
                if gewuenscht.strip() else Resolution("", None, False, NONE))
        # Written anew on every run, so a retry that hits the material clears an old miss.
        if gewuenscht.strip():
            db.set_instruction_unmatched("aia_mindmaps", mindmap_id, wahl.unmatched)
        # The summary goes by the source's own id, a source without chunks shifts the positions.
        summary_of: dict[int, str | None] = {}
        for suuid in source_uuids:
            source = db.get_aia_source(suuid)
            if source:
                summary_of[source["id"]] = source.get("summary")
        quellen = [{"id": sid, "label": label, "summary": summary_of.get(sid)}
                   for sid, label, _alle, _p in gesammelt]
        if wahl.chunks is not None:
            # Only the spots the instruction found, the full chunks stay for the timestamps.
            treffer = spots_by_source(wahl.chunks)
            gesammelt = [(sid, label, alle, treffer[sid])
                         for sid, label, alle, _p in gesammelt if sid in treffer]
        gesamt = sum(len(c.get("content") or "")
                     for _s, _l, alle, _p in gesammelt for c in alle)
        # A small model always goes the stepwise way, its single call would write too long.
        from src.features.ai_assistant.tasks._context_budget import small_model
        klein = small_model()
        # Everybody else gets one call, outline plus depth within the overview budget.
        verdichtet = wahl.chunks is None and klein and _condensed.usable(quellen)
        logger.info("mindmap {}: {} Zeichen Material, Weg {}", mindmap_id, gesamt,
                    "verdichtet" if verdichtet else "Volltext")

        context_parts, media_chunks_by_label = _source_context(gesammelt)
        if not context_parts:
            db.update_aia_mindmap(mindmap_id, "failed", error="Keine Inhalte vorhanden")
            return
        context = "\n\n".join(context_parts)

        # 2. Call LLM, through the shared tool client so the deadline and the thinking switch apply.
        from src.features.ai_assistant.tasks._helpers import _get_llm_client
        client, model, _ = _get_llm_client()
        # Every node names its file, a short tag instead of the name saves a fifth of the writing.
        tags = SourceTags([label for _sid, label, _alle, _p in gesammelt])

        # The level block hangs on the person, not on the course room. The instruction
        # travels with it so every call of both ways carries it.
        adaptive_suffix = (build_adaptive_tool_suffix(user_id)
                           + prompt_block(wahl.text, narrowed=wahl.chunks is not None))
        # Still needed below for the title's within-workspace deduplication.
        _first_source = db.get_aia_source(source_uuids[0]) if source_uuids else None
        from src.features.ai_assistant.tasks.studio._result_title import (
            free_title, recent_titles, title_rule,
        )
        vergeben = recent_titles("aia_mindmaps", (_first_source or {}).get("workspace_id"))
        messages = [
            {"role": "system", "content": AIA_MINDMAP_PROMPT.replace("{language}", language)
             + title_rule(language, vergeben) + adaptive_suffix},
            {"role": "user", "content": f"/no_think\nCreate a mind map from the following sources. Write topic and labels in {language}:\n\n{context}"},
        ]

        if verdichtet:
            mindmap = _build_stepwise(
                mindmap_id, client, model, tags, quellen, gesammelt,
                (_first_source or {}).get("workspace_id"), source_ids, language, adaptive_suffix)
        else:
            mindmap = _ask_json(client, model, messages, mindmap_id, tags=tags)

        if mindmap is None:
            db.update_aia_mindmap(mindmap_id, "failed", error="LLM returned unparseable JSON")
            return
        if not isinstance(mindmap, dict) or "topic" not in mindmap:
            db.update_aia_mindmap(mindmap_id, "failed", error="Invalid mindmap format")
            return

        _fix_media_nodes(mindmap, media_chunks_by_label)

        # The name comes out of the same answer, the root node stands in when it is missing.
        titel = free_title(mindmap.pop("title", ""), (mindmap.get("topic") or "").strip(),
                           vergeben) or None

        db.update_aia_mindmap(mindmap_id, "success", mindmap=mindmap, title=titel)
        logger.info("KI Tutor: mindmap {} generated successfully", mindmap_id)

    except Exception as e:
        from src.features.ai_assistant.tasks._warten import wieder_einreihen
        if wieder_einreihen(run_generate_mindmap, e, anlauf=anlauf, seit=seit,
                            args=[mindmap_id, source_ids, source_uuids],
                            kwargs={"locale": locale, "user_id": user_id, "_aia_job_uuid": _aia_job_uuid}):
            platz_weiter = True
            return
        logger.error("KI Tutor: mindmap {} generation failed: {}", mindmap_id, e)
        db.update_aia_mindmap(mindmap_id, "failed", error=str(e))
    finally:
        # A finished or failed small-model map needs no remembered steps any more.
        if klein and not platz_weiter:
            _Zwischenstand(mindmap_id).loeschen()
        if _aia_job_uuid and not platz_weiter:
            try:
                from src.features.ai_assistant.scheduling.service import on_complete
                on_complete(_aia_job_uuid)
            except Exception as e:
                logger.error("KI Tutor: mindmap dispatch on_complete failed: {}", e)
