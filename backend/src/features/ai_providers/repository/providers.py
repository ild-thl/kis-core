"""Database access to providers, one row per registered endpoint."""

import json
from datetime import datetime
from typing import Any, Optional

import psycopg2.extras

from src.core.db.pool import get_connection
from src.services import export_crypto

_COLUMNS = """id, name, protocol, base_url, api_key, capabilities,
                    voices, enabled, last_probed_at, probe_status, probe_error,
                    created_at, updated_at, concurrency, owner_user_id"""
_SELECT = f"SELECT {_COLUMNS}"

# Every list the admin area and the routing read leaves out the interfaces people set up for themselves.
_SHARED = "owner_user_id IS NULL"

# The buckets a provider can cap, a missing key in providers.concurrency means no cap.
CONCURRENCY_BUCKETS: tuple[str, ...] = ("llm", "stt", "tts", "image", "embedding", "ocr")

# A fixed label, not the provider's own name: renaming a provider must not
# break decrypting its stored key.
_AAD = "providers.api_key"


def _encrypt_key(raw: Optional[str]) -> Optional[str]:
    """Wraps a key for storage; passes it through unchanged without ASKF_SECRETS_KEY."""
    if raw is None or not export_crypto.is_export_key_configured():
        return raw
    return json.dumps(export_crypto.wrap_api_key(raw, provider_name=_AAD))


def _decrypt_key(stored: Optional[str]) -> Optional[str]:
    """Reverses _encrypt_key; a plain (pre-migration) string passes through unchanged."""
    if stored is None:
        return None
    try:
        envelope = json.loads(stored)
    except (TypeError, ValueError):
        return stored
    if not export_crypto.is_envelope(envelope):
        return stored
    return export_crypto.try_unwrap_api_key(envelope, provider_name=_AAD)


def _row_to_dict(row) -> dict:
    """Coerce a DictRow (mixed types from psycopg2) into a JSON-friendly dict."""
    d = dict(row)
    d["api_key"] = _decrypt_key(d.get("api_key"))
    for jsonb_col in ("capabilities", "voices"):
        v = d.get(jsonb_col)
        if isinstance(v, str):
            d[jsonb_col] = json.loads(v)
        elif v is None:
            d[jsonb_col] = []
    v = d.get("concurrency")
    if isinstance(v, str):
        d["concurrency"] = json.loads(v)
    elif v is None:
        d["concurrency"] = {}
    for ts in ("last_probed_at", "created_at", "updated_at"):
        v = d.get(ts)
        if isinstance(v, datetime):
            d[ts] = v.isoformat()
    return d


def list_providers() -> list[dict]:
    """All providers the admin set up, oldest first."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                f"""{_SELECT}
                   FROM providers
                   WHERE {_SHARED}
                   ORDER BY created_at ASC"""
            )
            return [_row_to_dict(r) for r in cur.fetchall()]


def get_provider(provider_id: int) -> Optional[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                f"""{_SELECT}
                   FROM providers WHERE id = %s""",
                (provider_id,),
            )
            row = cur.fetchone()
            return _row_to_dict(row) if row else None


def get_provider_by_name(name: str) -> Optional[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                f"""{_SELECT}
                   FROM providers WHERE name = %s""",
                (name,),
            )
            row = cur.fetchone()
            return _row_to_dict(row) if row else None


def create_provider(
    *,
    name: str,
    protocol: str,
    base_url: str,
    api_key: Optional[str] = None,
    capabilities: Optional[list[str]] = None,
    voices: Optional[list[dict]] = None,
    enabled: bool = True,
    concurrency: Optional[dict] = None,
    owner_user_id: Optional[int] = None,
) -> dict:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                f"""INSERT INTO providers
                       (name, protocol, base_url, api_key, capabilities, voices, enabled,
                        concurrency, owner_user_id)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s)
                   RETURNING {_COLUMNS}""",
                (
                    name,
                    protocol,
                    base_url,
                    _encrypt_key(api_key),
                    json.dumps(capabilities or []),
                    json.dumps(voices or []),
                    enabled,
                    json.dumps(concurrency or {}),
                    owner_user_id,
                ),
            )
            conn.commit()
            return _row_to_dict(cur.fetchone())


def update_provider(provider_id: int, **fields: Any) -> Optional[dict]:
    """Patch any column listed in allowed, concurrency replaces the whole object."""
    allowed = {"name", "protocol", "base_url", "api_key", "capabilities", "voices", "enabled",
               "concurrency"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_provider(provider_id)

    sets: list[str] = []
    values: list[Any] = []
    for key, value in updates.items():
        if key in ("capabilities", "voices"):
            sets.append(f"{key} = %s::jsonb")
            values.append(json.dumps(value or []))
        elif key == "concurrency":
            sets.append(f"{key} = %s::jsonb")
            values.append(json.dumps(value or {}))
        elif key == "api_key":
            sets.append(f"{key} = %s")
            values.append(_encrypt_key(value))
        else:
            sets.append(f"{key} = %s")
            values.append(value)
    sets.append("updated_at = NOW()")
    values.append(provider_id)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                f"""UPDATE providers SET {", ".join(sets)} WHERE id = %s
                    RETURNING {_COLUMNS}""",
                values,
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_dict(row) if row else None


def set_probe_result(
    provider_id: int,
    *,
    capabilities: list[str],
    status: str,
    error: Optional[str] = None,
) -> None:
    """Record the result of an auto-probe run on a provider."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE providers
                   SET capabilities = %s::jsonb,
                       last_probed_at = NOW(),
                       probe_status = %s,
                       probe_error = %s,
                       updated_at = NOW()
                   WHERE id = %s""",
                (json.dumps(capabilities), status, error, provider_id),
            )
            conn.commit()


def delete_provider(provider_id: int) -> bool:
    """Deletes a provider, its routes are left unconfigured."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM providers WHERE id = %s", (provider_id,))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted


def list_providers_with_capability(capability: str) -> list[dict]:
    """Providers whose capabilities array contains the given capability and which are enabled."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                f"""{_SELECT}
                   FROM providers
                   WHERE enabled = TRUE
                     AND capabilities ? %s
                     AND {_SHARED}
                   ORDER BY created_at ASC""",
                (capability,),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]


def list_own_providers(user_id: int) -> list[dict]:
    """The interfaces this person set up for themselves, oldest first."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                f"""{_SELECT}
                   FROM providers
                   WHERE owner_user_id = %s
                   ORDER BY created_at ASC""",
                (user_id,),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]


def delete_all_providers() -> int:
    """Deletes every provider the admin set up, people's own interfaces stay. Returns count deleted."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM providers WHERE {_SHARED}")
            deleted = cur.rowcount
            conn.commit()
            return deleted
