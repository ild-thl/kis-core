"""One door to every AI provider: each call takes a seat, a full or silent first choice hands over down the list."""

from __future__ import annotations

import asyncio
import contextvars
import email.utils
import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional

import httpx
from loguru import logger

try:
    # The OpenAI SDK 3.x speaks httpx2, a separate package with the same interface as httpx.
    import httpx2 as _sdk_http
except ImportError:  # pragma: no cover - older SDKs use httpx itself
    _sdk_http = httpx

from src.limits import (
    AIA_TOOL_SEAT_WAIT_SECONDS,
    LLM_LARGE_INPUT_CHARS,
    LLM_LARGE_INPUT_SHARE,
    PROVIDER_DOWN_SECONDS,
    PROVIDER_SEAT_WAIT_SECONDS,
)
from src.services import provider_slots

# Every feature counts against one field of its provider, image understanding with the LLM.
FEATURE_BUCKET: dict[str, str] = {
    "chat": "llm",
    "doc_translate": "llm",
    "transcript_translate": "llm",
    "vision": "llm",
    "stt": "stt",
    "tts": "tts",
    "image_gen": "image",
    "image_edit": "image",
    "embedding": "embedding",
    "ocr": "ocr",
}
BUCKETS: tuple[str, ...] = ("llm", "stt", "tts", "image", "embedding", "ocr")

# A voice only exists at its own provider, so speech output never falls back.
NO_FALLBACK_FEATURES = frozenset({"tts"})

# Answers that say the provider cannot serve right now, as opposed to a broken request.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_DOWN_KEY = "askf:provider-down:{}:{}"
# A held seat is renewed every 20 s, so one left unrenewed this long belongs to a process that died.
_SEAT_STALE_SECONDS = provider_slots.HELD_STALE_SECONDS
# A first choice that is not there has to be noticed fast, otherwise the fallback helps nobody.
_CONNECT_TIMEOUT = 10.0
# The body leaves in pieces like the SDK sends it, a single write would have to finish within the write timeout.
_PIECE = 64 * 1024
# GWDG chooses an image edit model by this header instead of the model field.
INFERENCE_SERVICE_HEADER = "inference-service"
_MULTIPART_MODEL = re.compile(rb'(name="model"\r\n(?:[^\r\n]+\r\n)*\r\n)(.*?)(\r\n--)', re.S)

_exempt: contextvars.ContextVar[bool] = contextvars.ContextVar("provider_seat_exempt", default=False)

# The rank this process queues with at the door, a worker runs one job at a time and sets it per job.
_rank = 0

# How long the calls of this process wait for a seat, None takes the default, set per job like the rank.
_seat_wait: Optional[float] = None

# Who really answered in the current job of this process, None while no job records it.
_answered: Optional[list[str]] = None

try:
    from openai import OpenAIError as _SdkError
except ImportError:  # pragma: no cover - the SDK is always installed in the containers
    _SdkError = Exception


class SeatsFull(provider_slots.ProviderFull, _SdkError):
    """A full provider that the OpenAI SDK passes on as it is, instead of waiting twice more."""


@contextmanager
def seat_exempt():
    """Calls inside take no seat, meant for the Francis chat a person waits for live."""
    token = _exempt.set(True)
    try:
        yield
    finally:
        _exempt.reset(token)


def exempt_this_request() -> None:
    """Frees the rest of the current request from seats, its streaming task inherits the mark."""
    _exempt.set(True)


def seat_rank_for(queue: Optional[str], priority: Optional[int]) -> int:
    """Quick services first, then tools and sources, then long services, continued stages and resumes."""
    if queue == "long" or (queue == "general" and (priority or 0) >= 9):
        return 2
    if queue in ("aia", "aia_ingest", "tts", "screencast"):
        return 1
    return 0


def set_seat_rank(rank: int) -> None:
    """Sets the rank for every call of this process until the next job sets its own."""
    global _rank
    _rank = rank


def seat_wait_for(queue: Optional[str]) -> Optional[float]:
    """A tutor tool waits longer in line, None keeps the default for everyone else."""
    return AIA_TOOL_SEAT_WAIT_SECONDS if queue == "aia" else None


def set_seat_wait(seconds: Optional[float]) -> None:
    """Sets the seat wait for every call of this process until the next job sets its own."""
    global _seat_wait
    _seat_wait = seconds


def _default_seat_wait() -> float:
    """The seat wait of this process, the general one unless the job set its own."""
    return PROVIDER_SEAT_WAIT_SECONDS if _seat_wait is None else _seat_wait


def record_answering() -> None:
    """Starts a fresh list of the providers that really answer, called when a job starts."""
    global _answered
    _answered = []


def answered() -> list[str]:
    """The providers that answered so far in this process's job, in the order they first did."""
    return list(_answered or [])


def _root(base_url: str) -> str:
    """The address without a trailing /v1, the part two providers differ in."""
    url = (base_url or "").rstrip("/")
    return url[:-3] if url.endswith("/v1") else url


@dataclass(frozen=True)
class Target:
    """One provider as the door sees it."""

    provider_id: int
    name: str
    root: str
    api_key: str
    model: str
    caps: dict = field(default_factory=dict, hash=False)

    @classmethod
    def of(cls, provider: dict, model: Optional[str]) -> "Target":
        return cls(
            provider_id=provider.get("id") or 0,
            name=provider.get("name") or "",
            root=_root(provider["base_url"]),
            api_key=provider.get("api_key") or "not-needed",
            model=model or "",
            caps=dict(provider.get("concurrency") or {}),
        )


def fallback_target(feature: str, primary_id: int, primary_model: str = "") -> Optional[Target]:
    """The admin's fallback for this feature, or None when there is none or it cannot serve."""
    if feature in NO_FALLBACK_FEATURES:
        return None
    from src import database as db

    try:
        route = db.get_route(feature) or {}
        fallback_id = route.get("fallback_provider_id")
        if not fallback_id or fallback_id == primary_id:
            return None
        provider = db.get_provider(fallback_id)
    except Exception as e:  # noqa: BLE001 - without the database the call simply has no fallback
        logger.warning("Rückfall für {} nicht lesbar: {}", feature, e)
        return None
    if not provider or not provider.get("enabled") or provider.get("protocol") != "openai_compat":
        return None
    model = (route.get("provider_models") or {}).get(str(fallback_id)) or ""
    if not model or (feature == "embedding" and primary_model and model != primary_model):
        # Another embedding model would put the answers into a different vector space.
        return None
    return Target.of(provider, model)


def further_targets(feature: str, skip: set[int], primary_model: str = "") -> list[Target]:
    """Every other provider the admin gave a model for this feature, in the admin's order for it."""
    if feature in NO_FALLBACK_FEATURES:
        return []
    from src import database as db
    from src.features.ai_providers.repository.feature_routes import FALLBACK_CAPABILITY

    capability = FALLBACK_CAPABILITY.get(feature)
    if not capability:
        return []
    try:
        route = db.get_route(feature) or {}
        models = route.get("provider_models") or {}
        providers = db.list_providers_with_capability(capability)
        stelle = {pid: i for i, pid in enumerate(db.ordered_ids(route, [p.get("id") for p in providers]))}
        providers = sorted(providers, key=lambda p: stelle.get(p.get("id"), len(stelle)))
    except Exception as e:  # noqa: BLE001 - without the database the call simply asks nobody further
        logger.warning("Weitere Anbieter für {} nicht lesbar: {}", feature, e)
        return []
    targets = []
    for provider in providers:
        model = models.get(str(provider.get("id"))) or ""
        if provider.get("id") in skip or not model or provider.get("protocol") != "openai_compat":
            continue
        if capability not in (provider.get("capabilities") or []) or not provider.get("enabled"):
            continue
        if feature == "embedding" and primary_model and model != primary_model:
            continue
        targets.append(Target.of(provider, model))
    return targets


def _targets(binding) -> tuple[Target, Optional[Target], str, list[Target]]:
    """First choice, the admin's fallback, the field the call counts against and whoever else may step in."""
    primary = Target.of(binding.provider, binding.model)
    second = fallback_target(binding.feature, primary.provider_id, primary.model)
    # Every provider with a model for the feature may step in, the admin's fallback only goes first.
    skip = {primary.provider_id} | ({second.provider_id} if second else set())
    rest = further_targets(binding.feature, skip, primary.model)
    return primary, second, FEATURE_BUCKET.get(binding.feature, binding.feature), rest


def transport_for(binding) -> "ProviderTransport":
    """The door for a plain httpx client, used for pictures and speech output."""
    return ProviderTransport(*_targets(binding))


def sdk_clients(binding) -> dict:
    """Both HTTP clients for an OpenAI SDK client, with the SDK's own defaults around the door."""
    from openai import DefaultAsyncHttpxClient, DefaultHttpxClient

    targets = _targets(binding)
    return {
        "http_client": DefaultHttpxClient(transport=SdkTransport(*targets)),
        "async_http_client": DefaultAsyncHttpxClient(transport=AsyncSdkTransport(*targets)),
    }


def sdk_http_client(binding):
    """The synchronous HTTP client for a plain OpenAI SDK client."""
    from openai import DefaultHttpxClient

    return DefaultHttpxClient(transport=SdkTransport(*_targets(binding)))


# ─── Shared state in Redis ─────────────────────────────────────────────────

_redis_client = None
_redis_pid = None


def _redis():
    """One Redis connection per process, a forked worker opens its own."""
    global _redis_client, _redis_pid
    if _redis_client is None or _redis_pid != os.getpid():
        _redis_client = provider_slots._redis()
        _redis_pid = os.getpid()
    return _redis_client


def is_down(provider_id: int, bucket: str) -> bool:
    """Whether a failed call left a note on this provider a moment ago, also read at the start of a voice job."""
    try:
        return bool(_redis().exists(_DOWN_KEY.format(provider_id, bucket)))
    except Exception:  # noqa: BLE001 - without Redis every provider counts as there
        return False


def _is_down(target: Target, bucket: str) -> bool:
    return is_down(target.provider_id, bucket)


def _mark_down(target: Target, bucket: str, seconds: float, why: str) -> None:
    logger.warning("Anbieter {} ({}) antwortet nicht ({}), {:.0f} s lang zweite Wahl",
                   target.name, bucket, why, seconds)
    try:
        _redis().set(_DOWN_KEY.format(target.provider_id, bucket), why[:100], ex=max(1, int(seconds)))
    except Exception as e:  # noqa: BLE001 - then the next call just tries the first choice again
        logger.warning("Sperrvermerk nicht gespeichert: {}", e)


def _answers(target: Target) -> bool:
    """Whether the provider answers a small request right now, so a slow call is told apart from a dead provider."""
    try:
        response = httpx.get(f"{target.root}/v1/models", headers={"Authorization": f"Bearer {target.api_key}"},
                             timeout=3.0)
        return response.status_code < 500
    except httpx.HTTPError:
        return False


def _down_seconds(response) -> float:
    """How long the provider itself wants to be left alone, otherwise the default."""
    for name in ("retry-after", "ratelimit-reset", "x-ratelimit-reset"):
        value = response.headers.get(name)
        if not value:
            continue
        try:
            seconds = float(value)
        except ValueError:
            try:
                seconds = email.utils.parsedate_to_datetime(value).timestamp() - time.time()
            except (TypeError, ValueError):
                continue
        return min(max(seconds, 5.0), 3600.0)
    return float(PROVIDER_DOWN_SECONDS)


# ─── The request itself ────────────────────────────────────────────────────


def _text_chars(body: bytes) -> int:
    """How much text a JSON call carries, pictures do not count."""
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0
    total = 0
    for message in data.get("messages") or []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(len(p.get("text") or "") for p in content if isinstance(p, dict))
    for name in ("input", "prompt"):
        value = data.get(name)
        if isinstance(value, str):
            total += len(value)
        elif isinstance(value, list):
            total += sum(len(v) for v in value if isinstance(v, str))
    return total


def moved_to(response, root: str) -> Optional[str]:
    """Where a provider moved the call on its own host, kept on https (GWDG sends image edits to http)."""
    if response.status_code not in (307, 308):
        return None
    location = httpx.URL(response.headers.get("location", ""))
    base = httpx.URL(root)
    if location.host and location.host != base.host:
        return None
    return str(base.copy_with(path=location.path, query=location.query or None))


def _with_model(body: bytes, content_type: str, model: str) -> bytes:
    """The same body with the fallback's model name, JSON or a multipart form."""
    if not model:
        return body
    if "application/json" in content_type:
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return body
        if isinstance(data, dict) and "model" in data:
            data["model"] = model
            return json.dumps(data, ensure_ascii=False).encode("utf-8")
        return body
    if "multipart/form-data" in content_type:
        return _MULTIPART_MODEL.sub(lambda m: m.group(1) + model.encode() + m.group(3), body, count=1)
    return body


def _with_think_off(body: bytes, target: Target) -> bytes:
    """The fallback's own switch against thinking instead of the first choice's, once its model was measured."""
    from src.services import model_limits
    profile = model_limits.stored_profile(target.provider_id, target.model)
    if profile is None:
        return body
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    if not isinstance(data, dict):
        return body
    for switch in model_limits.THINK_OFF_SWITCHES.values():
        for key, value in switch.items():
            if data.get(key) == value:
                data.pop(key)
    data.update(model_limits.think_off_body(profile))
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


class _Door:
    """Everything both transports share: order, seats, rewriting and the memory of who failed."""

    def __init__(self, primary: Target, fallback: Optional[Target], bucket: str, extras=()):
        self.primary = primary
        self.fallback = fallback
        self.bucket = bucket
        # The admin's fallback first, then the other providers from the admin list.
        self.backups = ([fallback] if fallback is not None else []) + list(extras)

    def serves(self, request) -> bool:
        return bool(self.primary.root) and str(request.url).startswith(self.primary.root)

    def order(self) -> list[Target]:
        """The first choice first, one that failed a moment ago behind the others."""
        if not self.backups:
            return [self.primary]
        everyone = [self.primary, *self.backups]
        there = [t for t in everyone if not _is_down(t, self.bucket)]
        # A provider with a note stays as a last try, a slow answer must not leave only dead ones.
        return there + [t for t in everyone if t not in there]

    def prepare(self, request, body: bytes, target: Target):
        """The request for this provider, with a short connect wait when a fallback stands by."""
        extensions = dict(request.extensions)
        if self.backups:
            timeout = dict(extensions.get("timeout") or {})
            timeout["connect"] = min(timeout.get("connect") or _CONNECT_TIMEOUT, _CONNECT_TIMEOUT)
            extensions["timeout"] = timeout
        if target is self.primary:
            request.extensions = extensions
            return request
        headers = [(k, v) for k, v in request.headers.multi_items()
                   if k.lower() not in ("host", "content-length", "authorization")]
        headers.append(("authorization", f"Bearer {target.api_key}"))
        # A call that names its model in the header names the fallback's model there too.
        headers = [(k, target.model if k.lower() == INFERENCE_SERVICE_HEADER else v) for k, v in headers]
        url = target.root + str(request.url)[len(self.primary.root):]
        content_type = request.headers.get("content-type", "")
        content = _with_model(body, content_type, target.model)
        if self.bucket == "llm" and "application/json" in content_type:
            content = _with_think_off(content, target)
        return type(request)(request.method, url, headers=headers, content=content, extensions=extensions)

    def seats(self, target: Target, body: bytes) -> list[tuple[str, int]]:
        """Which seats this call needs, a call with a lot of material one of the few large ones too."""
        cap = target.caps.get(self.bucket)
        if not cap or _exempt.get():
            return []
        cap = self._shared_cap(target, int(cap))
        wanted = []
        if self.bucket == "llm" and _text_chars(body) >= LLM_LARGE_INPUT_CHARS:
            wanted.append((f"{target.provider_id}:llm:large", max(1, int(cap) // LLM_LARGE_INPUT_SHARE)))
        wanted.append((f"{target.provider_id}:{self.bucket}", int(cap)))
        return wanted

    def _shared_cap(self, target: Target, cap: int) -> int:
        """A provider that is down hands its LLM seats to the ones still answering, each at most doubles."""
        if self.bucket != "llm" or not self.backups:
            return cap
        caps = [(t, int(t.caps.get(self.bucket) or 0)) for t in (self.primary, *self.backups)]
        # An uncapped provider in the line takes any overflow anyway.
        if any(c <= 0 for _t, c in caps):
            return cap
        alle = sum(c for _t, c in caps)
        da = sum(c for t, c in caps if not _is_down(t, self.bucket))
        if not da or da >= alle:
            return cap
        return min(cap * 2, max(cap, round(cap * alle / da)))

    def served(self, target: Target) -> None:
        """Names the provider that really answered, the SDK's own log line only knows the first choice."""
        if _answered is not None and target.name and target.name not in _answered:
            _answered.append(target.name)
        if target is not self.primary:
            logger.info("{} hat für {} geantwortet ({})", target.name, self.primary.name, self.bucket)

    def switch(self, target: Target, seconds: float, why: str, last: bool, alive: bool = False) -> bool:
        """Notes the failure when a fallback stands by, and tells whether another provider is left to ask."""
        # Voices never switch inside a job, the note only lets the next job start with the fallback.
        if (self.backups or self.bucket == "tts") and not alive:
            _mark_down(target, self.bucket, seconds, why)
        elif alive:
            logger.info("Anbieter {} ({}) war für einen Aufruf zu langsam, antwortet aber, kein Sperrvermerk",
                        target.name, self.bucket)
        return not last

    def spill_targets(self, order: list[Target]) -> list[Target]:
        """Where an LLM call may go instead of waiting when its first choice is full, in the admin's order."""
        if self.bucket != "llm" or _exempt.get() or len(order) < 2:
            return []
        return [t for t in order[1:] if not _is_down(t, self.bucket)]

    def slow_but_alive(self, target: Target, error: Exception, lib) -> bool:
        """A call that reached the provider and then broke spares a provider that still answers."""
        reached = not isinstance(error, (lib.ConnectError, lib.ConnectTimeout))
        return reached and bool(self.backups or self.bucket == "tts") and _answers(target)


def _releaser(held: list[tuple[str, str]]):
    """Gives the seats back exactly once."""
    done = []

    def release() -> None:
        if done:
            return
        done.append(True)
        for key, ticket in held:
            provider_slots.release(key, ticket)
    return release


def _build(lib, full=provider_slots.ProviderFull):
    """Both transports for one HTTP library, so plain httpx clients and the SDK's httpx2 share one door."""

    class _Pieces(lib.SyncByteStream, lib.AsyncByteStream):
        """A body read into memory, sent again in small pieces."""

        def __init__(self, data: bytes):
            self._data = data

        def __iter__(self):
            for i in range(0, len(self._data), _PIECE):
                yield self._data[i:i + _PIECE]

        async def __aiter__(self):
            for i in range(0, len(self._data), _PIECE):
                yield self._data[i:i + _PIECE]

    class _ReleasingStream(lib.SyncByteStream):
        def __init__(self, stream, release):
            self._stream, self._release = stream, release

        def __iter__(self):
            yield from self._stream

        def close(self) -> None:
            try:
                self._stream.close()
            finally:
                self._release()

    class _AsyncReleasingStream(lib.AsyncByteStream):
        def __init__(self, stream, release):
            self._stream, self._release = stream, release

        async def __aiter__(self):
            async for chunk in self._stream:
                yield chunk

        async def aclose(self) -> None:
            try:
                await self._stream.aclose()
            finally:
                self._release()

    class ProviderTransport(lib.BaseTransport):
        """The synchronous door, installed in every client that talks to a provider."""

        def __init__(self, primary: Target, fallback: Optional[Target], bucket: str, extras=(), inner=None):
            self._door = _Door(primary, fallback, bucket, extras)
            self._inner = inner or lib.HTTPTransport()

        def _take(self, wanted: list[tuple[str, int]], wait: Optional[float] = None) -> list[tuple[str, str]]:
            held: list[tuple[str, str]] = []
            try:
                for key, limit in wanted:
                    held.append((key, provider_slots.claim_ranked(
                        key, limit=limit, wait_seconds=_default_seat_wait() if wait is None else wait, rank=_rank,
                        stale_seconds=_SEAT_STALE_SECONDS)))
            except provider_slots.ProviderFull as e:
                _releaser(held)()
                raise full(e.provider, e.waited) from None
            except BaseException:
                # A time limit struck while waiting, the seats already taken go back.
                _releaser(held)()
                raise
            return held

        def _first_seat(self, order: list[Target], body: bytes):
            """An LLM call finding its first choice full takes the next free seat down the list instead of waiting."""
            door = self._door
            spill = door.spill_targets(order)
            for target in ([order[0], *spill] if spill else []):
                try:
                    held = self._take(door.seats(target, body), wait=0)
                except provider_slots.ProviderFull:
                    continue
                if target is not order[0]:
                    logger.info("{} ist voll, {} übernimmt ({})", order[0].name, target.name, door.bucket)
                return [target, *[t for t in order if t is not target]], held
            return order, None

        def handle_request(self, request):
            door = self._door
            if not door.serves(request):
                return self._inner.handle_request(request)
            body = request.read()
            order, held = self._first_seat(door.order(), body)
            for i, target in enumerate(order):
                last = i == len(order) - 1
                seats = held if i == 0 and held is not None else self._take(door.seats(target, body))
                release = _releaser(seats)
                try:
                    outgoing = door.prepare(request, body, target)
                    outgoing.stream = _Pieces(outgoing.content)
                    response = self._inner.handle_request(outgoing)
                    url = moved_to(response, target.root)
                    if url:
                        response.read()
                        response.close()
                        headers = [(k, v) for k, v in outgoing.headers.multi_items() if k.lower() != "host"]
                        # The rewritten body goes along, a fallback keeps its own model after the move.
                        outgoing = type(outgoing)(outgoing.method, url, headers=headers, content=outgoing.content,
                                                  extensions=outgoing.extensions)
                        outgoing.stream = _Pieces(outgoing.content)
                        response = self._inner.handle_request(outgoing)
                except lib.TransportError as e:
                    release()
                    alive = door.slow_but_alive(target, e, lib)
                    if door.switch(target, PROVIDER_DOWN_SECONDS, type(e).__name__, last, alive):
                        continue
                    raise
                except BaseException:
                    # A time limit or any other error mid call, the seat must not stay held for good.
                    release()
                    raise
                if response.status_code in _RETRY_STATUS:
                    if door.switch(target, _down_seconds(response), str(response.status_code), last):
                        release()
                        response.read()
                        response.close()
                        continue
                if response.is_closed:
                    # A body that is already complete never calls close, so the seat goes back now.
                    release()
                else:
                    response.stream = _ReleasingStream(response.stream, release)
                door.served(target)
                return response
            raise RuntimeError("provider door without a target")  # pragma: no cover

        def close(self) -> None:
            self._inner.close()

    class AsyncProviderTransport(lib.AsyncBaseTransport):
        """The asynchronous door, for the streaming chat and the summary."""

        def __init__(self, primary: Target, fallback: Optional[Target], bucket: str, extras=(), inner=None):
            self._door = _Door(primary, fallback, bucket, extras)
            self._inner = inner or lib.AsyncHTTPTransport()

        async def _take(self, wanted: list[tuple[str, int]], wait: Optional[float] = None) -> list[tuple[str, str]]:
            held: list[tuple[str, str]] = []
            try:
                for key, limit in wanted:
                    held.append((key, await provider_slots.claim_ranked_async(
                        key, limit=limit, wait_seconds=_default_seat_wait() if wait is None else wait, rank=_rank,
                        stale_seconds=_SEAT_STALE_SECONDS)))
            except provider_slots.ProviderFull as e:
                _releaser(held)()
                raise full(e.provider, e.waited) from None
            except BaseException:
                # A time limit struck while waiting, the seats already taken go back.
                _releaser(held)()
                raise
            return held

        async def _first_seat(self, order: list[Target], body: bytes):
            """An LLM call finding its first choice full takes the next free seat down the list instead of waiting."""
            door = self._door
            spill = door.spill_targets(order)
            for target in ([order[0], *spill] if spill else []):
                try:
                    held = await self._take(door.seats(target, body), wait=0)
                except provider_slots.ProviderFull:
                    continue
                if target is not order[0]:
                    logger.info("{} ist voll, {} übernimmt ({})", order[0].name, target.name, door.bucket)
                return [target, *[t for t in order if t is not target]], held
            return order, None

        async def handle_async_request(self, request):
            door = self._door
            if not door.serves(request):
                return await self._inner.handle_async_request(request)
            body = await request.aread()
            order, held = await self._first_seat(door.order(), body)
            for i, target in enumerate(order):
                last = i == len(order) - 1
                seats = held if i == 0 and held is not None else await self._take(door.seats(target, body))
                release = _releaser(seats)
                try:
                    outgoing = door.prepare(request, body, target)
                    outgoing.stream = _Pieces(outgoing.content)
                    response = await self._inner.handle_async_request(outgoing)
                except lib.TransportError as e:
                    release()
                    alive = await asyncio.to_thread(door.slow_but_alive, target, e, lib)
                    if door.switch(target, PROVIDER_DOWN_SECONDS, type(e).__name__, last, alive):
                        continue
                    raise
                except BaseException:
                    # A cancelled request or any other error mid call, the seat must not stay held for good.
                    release()
                    raise
                if response.status_code in _RETRY_STATUS:
                    if door.switch(target, _down_seconds(response), str(response.status_code), last):
                        release()
                        await response.aread()
                        await response.aclose()
                        continue
                if response.is_closed:
                    # A body that is already complete never calls close, so the seat goes back now.
                    release()
                else:
                    response.stream = _AsyncReleasingStream(response.stream, release)
                door.served(target)
                return response
            raise RuntimeError("provider door without a target")  # pragma: no cover

        async def aclose(self) -> None:
            await self._inner.aclose()

    return ProviderTransport, AsyncProviderTransport


# Plain httpx clients, for pictures and speech output.
ProviderTransport, AsyncProviderTransport = _build(httpx)
# The OpenAI SDK's clients, for the LLM, speech recognition, embeddings and text recognition.
SdkTransport, AsyncSdkTransport = _build(_sdk_http, SeatsFull)
