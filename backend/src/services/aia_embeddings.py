"""The embedding provider, chosen through the admin route."""

import json
import re
import time
from abc import ABC, abstractmethod

from loguru import logger

from src.limits import AIA_EMBEDDING_BATCH_SIZE

# How often an oversized batch is halved before the call gives up.
_MAX_SHRINKS = 3
# Pause before the second attempt when the provider waves off.
_RATE_LIMIT_PAUSE_SECONDS = 3
# How often a timeout is retried at the same size.
_MAX_TIMEOUT_RETRIES = 1

# Batch sizes learned from the endpoint, only really accepted ones are remembered.
_learned_batch_size: dict[tuple[str, str], int] = {}


def _is_rate_limited(e: Exception) -> bool:
    """True when the refusal is due to a full quota and not to the size."""
    if getattr(e, "status_code", None) == 429:
        return True
    text = str(e).lower()
    return "429" in text or "rate limit" in text


def _is_timeout(e: Exception) -> bool:
    """True when the far end did not answer at all."""
    if type(e).__name__ in ("APITimeoutError", "APIConnectionError", "TimeoutError"):
        return True
    text = str(e).lower()
    return "timed out" in text or "timeout" in text or "connection error" in text


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts and return a list of embedding vectors."""
        ...

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    @property
    def model_name(self) -> str:
        """Configured model name - used for fingerprint metadata and logs."""
        return getattr(self, "_model", "")


class OpenAICompatEmbeddingProvider(EmbeddingProvider):
    """Einbettungs-Client fuer jeden OpenAI-vertraeglichen Endpunkt."""

    def __init__(self, base_url: str, api_key: str, model: str, *,
                 timeout: float = 60.0, retry_on_timeout: bool = True, http_client=None) -> None:
        from langfuse.openai import OpenAI
        # Generous timeout for cold starts, the retry rule lives in embed.
        self._client = OpenAI(api_key=api_key, base_url=base_url,
                              timeout=timeout, max_retries=0, http_client=http_client)
        self._model = model
        self._key = (base_url, model)
        self._retry_on_timeout = retry_on_timeout

    def _request(self, batch: list[str]) -> list[list[float]]:
        """One call against the endpoint, a separate method for the tests."""
        response = self._client.embeddings.create(model=self._model, input=batch)
        return [item.embedding for item in response.data]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embeds texts, the batch size is measured at the endpoint instead of configured."""
        size = _learned_batch_size.get(self._key, AIA_EMBEDDING_BATCH_SIZE)
        results: list[list[float]] = []
        pending = list(texts)
        shrinks = 0
        timeout_retries = 0
        darf_lernen = True

        while pending:
            batch = pending[:size]
            try:
                vectors = self._request(batch)
            except Exception as e:
                if _is_rate_limited(e):
                    logger.warning(
                        "Embedding: Kontingent voll bei {} Eingaben ({}), neuer Versuch in {}s",
                        len(batch), e, _RATE_LIMIT_PAUSE_SECONDS,
                    )
                    time.sleep(_RATE_LIMIT_PAUSE_SECONDS)
                    try:
                        vectors = self._request(batch)
                    except Exception as e2:
                        raise RuntimeError(f"Embedding request failed: {e2}") from e2
                else:
                    if _is_timeout(e):
                        # Whoever waits for a result gets the refusal right away.
                        if not self._retry_on_timeout:
                            raise RuntimeError(f"Embedding request failed: {e}") from e
                        # In the background first the same size once more.
                        if timeout_retries < _MAX_TIMEOUT_RETRIES:
                            timeout_retries += 1
                            logger.warning(
                                "Embedding: Gegenstelle antwortet nicht bei {} Eingaben ({}), "
                                "gleiche Groesse noch einmal",
                                len(batch), e,
                            )
                            continue
                        # Too slow twice means the batch may be cut after all.
                    if size > 1 and shrinks < _MAX_SHRINKS:
                        shrinks += 1
                        # The next request has to be smaller than the rejected one.
                        size = max(1, size // 2)
                        if size >= len(batch):
                            # Emergency cut on the batch itself, without learning anything from it.
                            size = max(1, len(batch) // 2)
                            darf_lernen = False
                        logger.warning(
                            "Embedding: Endpunkt lehnt {} Eingaben ab ({}), neuer Versuch mit {}",
                            len(batch), e, size,
                        )
                        continue
                    raise RuntimeError(f"Embedding request failed: {e}") from e

            results.extend(vectors)
            pending = pending[len(batch):]
            # The retry budget applies per batch, not per call.
            timeout_retries = 0
            if darf_lernen and _learned_batch_size.get(self._key) != size:
                _learned_batch_size[self._key] = size

        return results


def _provider_from_binding(binding, *, timeout: float, retry_on_timeout: bool) -> OpenAICompatEmbeddingProvider:
    """Builds an embedding client for an already-resolved binding."""
    from src.services import feature_router, provider_transport

    provider = binding.provider
    return OpenAICompatEmbeddingProvider(
        base_url=feature_router._ensure_v1(provider["base_url"]),
        api_key=provider.get("api_key") or "not-needed",
        model=binding.model or "",
        timeout=timeout,
        retry_on_timeout=retry_on_timeout,
        http_client=provider_transport.sdk_http_client(binding),
    )


def get_embedding_provider(*, timeout: float = 60.0,
                           retry_on_timeout: bool = True) -> EmbeddingProvider:
    """The currently active embedding provider, without a route it raises."""
    from src.services import feature_router
    try:
        binding = feature_router.resolve("embedding")
    except feature_router.FeatureNotConfigured as e:
        raise RuntimeError(
            "Kein Embedding-Anbieter aktiv. Bitte im Admin-Bereich unter 'KI' den "
            "Anbieter für das Feature 'Embedding' setzen. (" + str(e) + ")"
        )
    return _provider_from_binding(binding, timeout=timeout, retry_on_timeout=retry_on_timeout)


class FallbackEmbeddingProvider(EmbeddingProvider):
    """Tries each embedding provider in order, moves on after a hard failure."""

    def __init__(self, providers: list[EmbeddingProvider]) -> None:
        if not providers:
            raise ValueError("FallbackEmbeddingProvider needs at least one provider")
        self._providers = providers

    @property
    def model_name(self) -> str:
        return self._providers[0].model_name

    def embed(self, texts: list[str]) -> list[list[float]]:
        last_err: Exception | None = None
        for i, provider in enumerate(self._providers):
            try:
                return provider.embed(texts)
            except RuntimeError as e:
                last_err = e
                is_last = i == len(self._providers) - 1
                logger.warning(
                    "Embedding-Anbieter gescheitert ({}), {}",
                    e, "keine weiteren Anbieter" if is_last else "wechsle zu naechstem Anbieter",
                )
        raise last_err


def get_embedding_provider_with_fallback(*, timeout: float = 60.0,
                                         retry_on_timeout: bool = True) -> EmbeddingProvider:
    """The active embedding provider, with same-model fallback providers behind it."""
    from src.services import feature_provider_choices
    primary = get_embedding_provider(timeout=timeout, retry_on_timeout=retry_on_timeout)
    fallbacks = feature_provider_choices.fallback_candidates("embedding")
    if not fallbacks:
        return primary
    providers = [primary] + [
        _provider_from_binding(b, timeout=timeout, retry_on_timeout=retry_on_timeout)
        for b in fallbacks
    ]
    return FallbackEmbeddingProvider(providers)


def fingerprint_from_dim(provider: EmbeddingProvider, dim: int) -> str:
    """Builds the fingerprint from an already known size, without a call."""
    return json.dumps({"model": provider.model_name, "dim": dim}, sort_keys=True)


def same_embedding_space(a: str, b: str) -> bool:
    """Equal size and model name apart from punctuation, Ollama writes qwen3-embedding:4b for qwen3-embedding-4b."""
    def key(fp: str):
        try:
            d = json.loads(fp)
            return re.sub(r"[^a-z0-9]", "", str(d.get("model", "")).lower()), d.get("dim")
        except (ValueError, AttributeError):
            return fp
    return key(a) == key(b)


def compute_fingerprint(provider: EmbeddingProvider) -> str:
    """The fingerprint of the embedding space from model name and size."""
    dim = len(provider.embed_one("askFrancis Embedding Fingerprint v1"))
    return fingerprint_from_dim(provider, dim)
