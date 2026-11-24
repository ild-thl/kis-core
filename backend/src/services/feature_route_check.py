"""Checks whether a configured route really works, with a real call."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Optional

import httpx
from loguru import logger

from src.services.model_limits import CHAT_LIKE_FEATURES as _CHAT_LIKE_FEATURES
from src.services.protocols import make_adapter
from src.services.protocols.deepl import DeepLAdapter
from src.services.protocols.docling import DoclingAdapter
from src.services.protocols.openai_compat import OpenAICompatAdapter
from src.services.provider_transport import INFERENCE_SERVICE_HEADER, moved_to


_TIMEOUT = 15.0


@dataclass
class FeatureTestResult:
    status: str  # "ok" | "error"
    error: Optional[str] = None
    # Soft signal next to 'ok', the call went through with a caveat.
    warning: Optional[str] = None


def run_feature_route_test(
    *,
    feature: str,
    protocol: str,
    base_url: str,
    api_key: Optional[str],
    model_name: Optional[str],
    voices: Optional[list] = None,
) -> FeatureTestResult:
    """Dispatch a feature-appropriate test request and report ok/error."""
    try:
        if protocol == OpenAICompatAdapter.PROTOCOL:
            return _test_openai_compat(
                feature=feature,
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
                voices=voices or [],
            )
        # Non-openai protocols are single-capability: probe IS the feature test.
        adapter = make_adapter(protocol=protocol, base_url=base_url, api_key=api_key)
        if isinstance(adapter, (DeepLAdapter, DoclingAdapter)):
            result = adapter.probe()
            return FeatureTestResult(status=result.status, error=result.error)
        return FeatureTestResult(status="error", error=f"unsupported protocol: {protocol}")
    except Exception as e:  # noqa: BLE001 - test must never crash the caller
        logger.exception("feature test crashed for protocol={} feature={}", protocol, feature)
        return FeatureTestResult(status="error", error=f"{type(e).__name__}: {e}")


# ─── OpenAI-compat per-feature tests ────────────────────────────────────────


def _auth_headers(api_key: Optional[str]) -> dict:
    h = {"Accept": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def _openai_headers(api_key: Optional[str]) -> dict:
    return {**_auth_headers(api_key), "Content-Type": "application/json"}


def _build_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1") and path.startswith("/v1/"):
        return base + path[len("/v1"):]
    return base + path


def _test_openai_compat(
    *,
    feature: str,
    base_url: str,
    api_key: Optional[str],
    model_name: Optional[str],
    voices: list,
) -> FeatureTestResult:
    if feature == "tts":
        # The model is optional for speech output, some providers reject it.
        if not voices:
            return FeatureTestResult(status="error", error="no_voices_configured")
        return _post_tts(base_url, api_key, model_name, voices)
    if feature == "stt":
        # A real call with a silence file so a wrong model shows up.
        if not model_name:
            return FeatureTestResult(status="error", error="model_name_not_set")
        return _post_stt(base_url, api_key, model_name)
    if feature in ("image_gen", "image_edit"):
        if not model_name:
            return FeatureTestResult(status="error", error="model_name_not_set")
        return _check_image_model(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            edit=feature == "image_edit",
        )
    if not model_name:
        return FeatureTestResult(status="error", error="model_name_not_set")
    if feature in _CHAT_LIKE_FEATURES:
        return _post_chat_completion(base_url, api_key, model_name)
    if feature == "embedding":
        return _post_embedding(base_url, api_key, model_name)
    return FeatureTestResult(status="error", error=f"unknown feature: {feature}")


def _post_chat_completion(
    base_url: str, api_key: Optional[str], model_name: str
) -> FeatureTestResult:
    url = _build_url(base_url, "/v1/chat/completions")
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    return _post_json(url, api_key, payload)


def _post_embedding(
    base_url: str, api_key: Optional[str], model_name: str
) -> FeatureTestResult:
    url = _build_url(base_url, "/v1/embeddings")
    payload = {"model": model_name, "input": "ping"}
    return _post_json(url, api_key, payload)


def _post_tts(
    base_url: str, api_key: Optional[str], model_name: Optional[str], voices: list
) -> FeatureTestResult:
    url = _build_url(base_url, "/v1/audio/speech")
    voice_id = voices[0]["voice_id"]
    payload: dict = {"input": "ping", "voice": voice_id}
    if model_name:
        payload["model"] = model_name
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(url, headers=_openai_headers(api_key), json=payload)
    except httpx.HTTPError:
        return FeatureTestResult(status="error", error="unreachable")
    result = _classify_http(resp)
    if result.status == "error" and resp.status_code == 404:
        return FeatureTestResult(status="error", error="tts_speech_endpoint_not_found")
    return result


def _silence_wav(duration_sec: float = 0.1, sample_rate: int = 16000) -> bytes:
    """Build a minimal mono 16-bit PCM WAV of silence for STT model probing."""
    num_samples = int(duration_sec * sample_rate)
    data_size = num_samples * 2
    byte_rate = sample_rate * 2
    return b"".join([
        b"RIFF",
        struct.pack("<I", 36 + data_size),
        b"WAVE",
        b"fmt ",
        struct.pack("<I", 16),
        struct.pack("<H", 1),
        struct.pack("<H", 1),
        struct.pack("<I", sample_rate),
        struct.pack("<I", byte_rate),
        struct.pack("<H", 2),
        struct.pack("<H", 16),
        b"data",
        struct.pack("<I", data_size),
        b"\x00" * data_size,
    ])


# An obviously wrong model name as bait.
_STT_CANARY_MODEL = "__askf_canary_invalid_model_xyz__"


def _stt_probe(
    base_url: str, api_key: Optional[str], model_name: str
) -> httpx.Response:
    url = _build_url(base_url, "/v1/audio/transcriptions")
    headers = _auth_headers(api_key)
    files = {"file": ("probe.wav", _silence_wav(), "audio/wav")}
    data = {"model": model_name, "response_format": "text"}
    with httpx.Client(timeout=_TIMEOUT) as client:
        return client.post(url, headers=headers, files=files, data=data)


def _has_real_backend_evidence(resp: httpx.Response) -> int:
    """Counts headers that prove the request reached a real service."""
    headers = {k.lower(): v for k, v in resp.headers.items()}
    n = 0
    if any(k.startswith("x-ratelimit-") or k.startswith("ratelimit-") for k in headers):
        n += 1
    if "x-kong-upstream-latency" in headers:
        n += 1
    if "via" in headers:
        n += 1
    if any(k in headers for k in ("x-request-id", "x-kong-request-id")):
        n += 1
    return n


def _post_stt(
    base_url: str, api_key: Optional[str], model_name: str
) -> FeatureTestResult:
    try:
        resp = _stt_probe(base_url, api_key, model_name)
    except httpx.HTTPError:
        return FeatureTestResult(status="error", error="unreachable")
    primary = _classify_http(resp)
    if primary.status != "ok":
        return primary
    # A bait call shows whether the provider reads the model name at all.
    try:
        canary = _stt_probe(base_url, api_key, _STT_CANARY_MODEL)
    except httpx.HTTPError:
        return primary
    if 200 <= canary.status_code < 300:
        evidence = _has_real_backend_evidence(resp)
        warning_key = (
            "stt_endpoint_verified_model_unvalidated"
            if evidence >= 2
            else "stt_model_not_validated_by_provider"
        )
        return FeatureTestResult(status="ok", warning=warning_key)
    return primary


def _make_grey_png(side: int = 64) -> bytes:
    """Builds a small grey PNG, some image readers rejected 1x1."""
    raw = b"".join(b"\x00" + b"\x80" * side for _ in range(side))
    z = zlib.compress(raw)

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body))
        )

    ihdr = struct.pack(">IIBBBBB", side, side, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", z)
        + chunk(b"IEND", b"")
    )


_TINY_PNG = _make_grey_png(64)

# Image generation may take longer, hence a generous timeout.
_IMAGE_TIMEOUT = 60.0


def _check_image_model(
    *, base_url: str, api_key: Optional[str], model_name: str, edit: bool
) -> FeatureTestResult:
    """Checks an image model with a real call, exactly as in operation."""
    headers = _auth_headers(api_key)
    try:
        with httpx.Client(timeout=_IMAGE_TIMEOUT, headers=headers) as client:
            if edit:
                # The same payload as in operation, otherwise the probe raises a false alarm.
                url = _build_url(base_url, "/v1/images/edits")
                form = {
                    "files": {"image": ("probe.png", _TINY_PNG, "image/png")},
                    "data": {
                        "model": model_name,
                        "prompt": "test",
                        "response_format": "b64_json",
                        "n": "1",
                        "size": "1024x1024",
                        "quality": "standard",
                        "guidance_scale": "3.5",
                        "num_inference_steps": "25",
                    },
                    "headers": {INFERENCE_SERVICE_HEADER: model_name},
                }
                resp = client.post(url, **form)
                moved = moved_to(resp, url)
                if moved:
                    resp = client.post(moved, **form)
            else:
                url = _build_url(base_url, "/v1/images/generations")
                payload = {
                    "model": model_name,
                    "prompt": "test",
                    "size": "256x256",
                    "n": 1,
                    "response_format": "b64_json",
                }
                resp = client.post(
                    url, headers={"Content-Type": "application/json"}, json=payload
                )
    except httpx.HTTPError:
        return FeatureTestResult(status="error", error="unreachable")
    return _classify_http(resp)


def _post_json(url: str, api_key: Optional[str], payload: dict) -> FeatureTestResult:
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(url, headers=_openai_headers(api_key), json=payload)
    except httpx.HTTPError:
        return FeatureTestResult(status="error", error="unreachable")
    return _classify_http(resp)


def _classify_http(resp: httpx.Response) -> FeatureTestResult:
    status = resp.status_code
    if 200 <= status < 300:
        return FeatureTestResult(status="ok")
    if status in (401, 403):
        return FeatureTestResult(status="error", error="auth_rejected")
    # Look in the body for a readable reason first, it says more.
    detail = ""
    try:
        body = resp.json()
        # OpenAI format: {"error": {"message": "..."}}
        err = body.get("error", {})
        if isinstance(err, dict):
            detail = err.get("message", "")
        # Some servers: {"detail": {"message": "..."}} or {"detail": "..."}
        if not detail:
            d = body.get("detail", "")
            if isinstance(d, dict):
                detail = d.get("message", "")
            elif isinstance(d, str):
                detail = d
        if not detail:
            detail = body.get("message", "")
    except Exception:
        pass
    # Plain-text body fallback (e.g. a plain "Model Not Found").
    if not detail and resp.text:
        detail = resp.text.strip()[:200]
    if detail:
        return FeatureTestResult(status="error", error=detail)
    if status >= 500:
        return FeatureTestResult(status="error", error="server_error")
    if status == 404:
        return FeatureTestResult(status="error", error="endpoint_not_found")
    return FeatureTestResult(status="error", error=f"http_{status}")
