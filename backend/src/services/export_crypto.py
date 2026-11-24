"""Verschluesselt Zugangsschluessel in Admin-Ausfuhren, gebunden an ihren Anbieter."""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ENVELOPE_ALG_V1 = "aesgcm-v1"
ENVELOPE_ALG_V2 = "aesgcm-v2"
CURRENT_ALG = ENVELOPE_ALG_V2


def _secret() -> str | None:
    raw = (os.environ.get("ASKF_SECRETS_KEY") or "").strip()
    return raw or None


def is_export_key_configured() -> bool:
    return _secret() is not None


def _derive_key(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def wrap_api_key(plain: str, *, provider_name: str) -> dict[str, str]:
    """Encrypts a plaintext and binds it to the provider name."""
    secret = _secret()
    if secret is None:
        raise RuntimeError("ASKF_SECRETS_KEY not configured")
    key = _derive_key(secret)
    nonce = os.urandom(12)
    aad = provider_name.encode("utf-8")
    ct = AESGCM(key).encrypt(nonce, plain.encode("utf-8"), aad)
    return {"alg": CURRENT_ALG, "nonce": _b64e(nonce), "ct": _b64e(ct)}


def is_envelope(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("alg") in (ENVELOPE_ALG_V1, ENVELOPE_ALG_V2)
        and isinstance(value.get("nonce"), str)
        and isinstance(value.get("ct"), str)
    )


def try_unwrap_api_key(
    envelope: dict[str, Any], *, provider_name: str
) -> str | None:
    """Decrypts an envelope, None when the key does not fit."""
    secret = _secret()
    if secret is None:
        return None
    try:
        key = _derive_key(secret)
        nonce = _b64d(envelope["nonce"])
        ct = _b64d(envelope["ct"])
        alg = envelope.get("alg")
        if alg == ENVELOPE_ALG_V2:
            aad = provider_name.encode("utf-8")
            pt = AESGCM(key).decrypt(nonce, ct, aad)
        elif alg == ENVELOPE_ALG_V1:
            pt = AESGCM(key).decrypt(nonce, ct, None)
        else:
            return None
        return pt.decode("utf-8")
    except Exception:
        return None
