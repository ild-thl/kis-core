"""Sends LaTeX paragraphs with markup tags to DeepL or an LLM and checks that every tag came back."""

import html
import re
from concurrent.futures import ThreadPoolExecutor

from loguru import logger

from src.services.deepl_client import DeepLClient
from src.services.llm_translation_client import (
    _BATCH_PARALLELISM,
    _BATCH_SYSTEM_PROMPT,
    _CHUNK_SIZE,
    _SYSTEM_PROMPT,
    LLMTranslationClient,
)
from src.services.translation import TranslationService

TAG_RE = re.compile(r"<(/?)([gx])(\d+)(/?)>")
_LOOSE_TAG_RE = re.compile(r"<\s*(/?)\s*([gxGX])\s*(\d+)\s*(/?)\s*>")

# DeepL takes at most 50 texts per request, the character cap keeps requests well below its size limit.
_DEEPL_MAX_TEXTS = 50
_DEEPL_MAX_CHARS = 60_000
_LLM_MAX_CHARS = 6_000

_TAG_RULES = (
    "The text comes from a LaTeX document, its markup is replaced by tags.\n"
    "- <x1/>, <x2/> and so on stand for formulas, references or commands. "
    "Copy each one exactly once and unchanged to the matching place.\n"
    "- <g1>...</g1> wraps formatted text such as bold words or a link. "
    "Translate the words inside and keep the pair around their translation.\n"
    "- Never add, drop, rename or renumber a tag.\n"
    "Example from German to English:\n"
    "Dies ist ein <g1>wichtiger</g1> Satz mit <x2/>, siehe <x3/>.\n"
    "This is an <g1>important</g1> sentence with <x2/>, see <x3/>.\n"
)


def tags_match(source: str, translated: str) -> bool:
    """True when the translation has exactly the source tags, properly nested, and some text."""
    src = TAG_RE.findall(source)
    out = TAG_RE.findall(translated)
    if sorted(src) != sorted(out):
        return False
    stack: list[str] = []
    for closing, kind, num, _self in out:
        if kind == "x":
            continue
        if not closing:
            stack.append(num)
        elif not stack or stack.pop() != num:
            return False
    if stack:
        return False
    has_text = bool(TAG_RE.sub("", source).strip())
    return not has_text or bool(TAG_RE.sub("", translated).strip())


def normalize_tags(text: str) -> str:
    """Repairs harmless tag spellings such as <x7> or </x7> that models write around quoted words."""
    def fix(m: re.Match) -> str:
        closing, kind, num = m.group(1), m.group(2).lower(), m.group(3)
        if kind == "x":
            return "" if closing else f"<x{num}/>"
        return f"</g{num}>" if closing else f"<g{num}>"
    return _LOOSE_TAG_RE.sub(fix, text)


def _map_text(tagged: str, fn) -> str:
    """Applies fn to the text between tags and leaves the tags alone."""
    out: list[str] = []
    pos = 0
    for m in TAG_RE.finditer(tagged):
        out.append(fn(tagged[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(fn(tagged[pos:]))
    return "".join(out)


def _instruction(source_lang: str, target_lang: str) -> str:
    if source_lang:
        return f"from {source_lang} to {target_lang}"
    return f"to {target_lang} (auto-detect source language)"


def _batches(texts: list[str], max_items: int, max_chars: int) -> list[list[int]]:
    batches: list[list[int]] = []
    current: list[int] = []
    size = 0
    for idx, text in enumerate(texts):
        if current and (len(current) >= max_items or size + len(text) > max_chars):
            batches.append(current)
            current, size = [], 0
        current.append(idx)
        size += len(text)
    if current:
        batches.append(current)
    return batches


def _via_deepl(client: DeepLClient, texts: list[str], source_lang: str, target_lang: str) -> list[str | None]:
    source = source_lang.split("-")[0] if source_lang else None
    results: list[str | None] = [None] * len(texts)
    for batch in _batches(texts, _DEEPL_MAX_TEXTS, _DEEPL_MAX_CHARS):
        escaped = [_map_text(texts[i], lambda s: html.escape(s, quote=False)) for i in batch]
        answer = client.raw.translate_text(
            escaped, source_lang=source, target_lang=target_lang,
            tag_handling="xml", outline_detection=False, split_sentences="nonewlines",
        )
        for i, r in zip(batch, answer):
            results[i] = _map_text(r.text, html.unescape)
    return results


def _llm_single(client: LLMTranslationClient, text: str, system: str) -> str | None:
    raw, finish = client._completion_with_retry(system, text)
    return None if finish == "length" else normalize_tags(raw.strip())


def _via_llm(client: LLMTranslationClient, texts: list[str], source_lang: str, target_lang: str) -> list[str | None]:
    instruction = _instruction(source_lang, target_lang)
    single_prompt = _SYSTEM_PROMPT.format(instruction=instruction) + _TAG_RULES
    batch_prompt = _BATCH_SYSTEM_PROMPT.format(instruction=instruction) + _TAG_RULES
    # Small local models do not keep the numbered format, so they get one call per paragraph.
    max_items = 1 if getattr(client, "_provider", "") == "local" else _CHUNK_SIZE

    def run(batch: list[int]) -> list[str | None]:
        items = [texts[i] for i in batch]
        if len(items) == 1:
            return [_llm_single(client, items[0], single_prompt)]
        numbered = "\n".join(f"{n + 1}. {t}" for n, t in enumerate(items))
        raw, finish = client._completion_with_retry(batch_prompt, numbered, item_count=len(items))
        parsed = [None] * len(items) if finish == "length" else client._parse_numbered(raw, len(items))[0]
        parsed = [normalize_tags(p) if p is not None else None for p in parsed]
        # An entry with missing or broken tags gets a second chance on its own.
        return [
            p if p is not None and tags_match(t, p) else _llm_single(client, t, single_prompt)
            for t, p in zip(items, parsed)
        ]

    batches = _batches(texts, max_items, _LLM_MAX_CHARS)
    results: list[str | None] = [None] * len(texts)
    with ThreadPoolExecutor(max_workers=max(1, min(len(batches), _BATCH_PARALLELISM))) as pool:
        for batch, answer in zip(batches, pool.map(run, batches)):
            for i, r in zip(batch, answer):
                results[i] = r
    return results


def translate_tagged(
    texts: list[str], source_lang: str, target_lang: str, service: TranslationService
) -> list[str | None]:
    """Translates tagged paragraphs, None marks an entry whose tags did not survive."""
    if not texts:
        return []
    glossary = service.glossary
    prepared: list[str] = []
    replacements: list[dict] = []
    for text in texts:
        p, r = glossary.apply_to_text(text)
        prepared.append(p)
        replacements.append(r)

    client = service.deepl_client
    if isinstance(client, DeepLClient):
        raw = _via_deepl(client, prepared, source_lang, target_lang)
    elif isinstance(client, LLMTranslationClient):
        raw = _via_llm(client, prepared, source_lang, target_lang)
    else:
        raw = [normalize_tags(client.translate_text(p, source_lang, target_lang)) for p in prepared]

    results: list[str | None] = []
    for text, out, reps in zip(texts, raw, replacements):
        restored = glossary.restore_text(out, reps) if out is not None else None
        results.append(restored if restored is not None and tags_match(text, restored) else None)
    failed = sum(1 for r in results if r is None)
    if failed:
        logger.warning("LaTeX: {}/{} paragraphs lost tags, translated piece by piece.", failed, len(texts))
    return results
