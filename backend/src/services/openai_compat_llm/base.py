"""Base class of the OpenAI-compat LLM client mixins + internal helpers."""

import json

import httpx
from langfuse.openai import AsyncOpenAI, OpenAI

# Waits as long as myLab lets a call run (about 300 s), the chat's silence timeout applies after the first character.
_LLM_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)


def is_transient_error(e: Exception) -> bool:
    """Match transient upstream failures worth retrying (5xx, 429 rate-limit, timeouts, connection errors)."""
    status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    if isinstance(status, int) and (500 <= status < 600 or status == 429):
        return True
    msg = str(e).lower()
    return any(kw in msg for kw in (
        "internal server error", "bad gateway", "service unavailable",
        "gateway timeout", "timeout", "connection", "temporarily",
        "rate limit", "429",
    ))


def load_prompt(key: str, default: str) -> str:
    """Load a system prompt from DB settings, falling back to the hardcoded default."""
    try:
        from src import database as db
        val = db.get_setting(key, "")
        return val if val.strip() else default
    except Exception:
        return default


def clean_whisper_response(raw: str) -> str:
    """Clean Whisper API response that may be JSON-encoded (wrapped in quotes with escaped newlines)."""
    text = raw.strip()
    # Some providers ignore response_format=text and answer with the JSON object instead.
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("text"), str):
            return parsed["text"].strip()
    if text.startswith('"') and text.endswith('"'):
        try:
            text = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            text = text[1:-1]
            text = text.replace("\\n", "\n").replace("\\r", "\r")
    return text.strip()


class _OpenAICompatBase:
    """The shared fields of all mixins, set by the actual class."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        whisper_model: str,
        provider: str = "openai_compat",
        http_client=None,
        async_http_client=None,
    ):
        # The HTTP clients carry the provider door with seats and fallback, see provider_transport.
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=_LLM_HTTP_TIMEOUT, http_client=http_client)
        # Async twin for streaming endpoints that need cancel-on-disconnect.
        self._async_client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=_LLM_HTTP_TIMEOUT,
                                         http_client=async_http_client)
        self._model = model
        self._provider = provider
        self._base_url = base_url
        self._whisper_model = whisper_model
        self._extra_body: dict = {}
        # Sampling values from the admin, empty means the built-in value applies.
        self._sampling: dict = {}
        # Batch settings for script generation.
        self._batch_max_workers: int = 3
        self._batch_timeout: float = 180.0
        self._batch_size: int = 3

    def sampling(self, standard: float) -> dict:
        """The admin values if set, else the built-in temperature."""
        werte = getattr(self, "_sampling", None)
        return dict(werte) if werte else {"temperature": standard}
