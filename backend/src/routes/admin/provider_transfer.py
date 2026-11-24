"""Export, import and wipe of the whole AI configuration, providers by name instead of id."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger

from src import database as db
from src.features.ai_providers.repository.feature_routes import FEATURES
from src.i18n import t
from src.routes.admin._models import ImportConfigRequest
from src.routes.admin._provider_shared import _concurrency_problem, _require
from src.services.export_crypto import (
    is_envelope,
    is_export_key_configured,
    try_unwrap_api_key,
    wrap_api_key,
)
from src.services.protocols import CAPABILITIES, known_protocols
from src.services.provider_probe import probe_provider

router = APIRouter(tags=["admin: providers"])

SCHEMA_VERSION = 1


def _keyed_by_name(by_id: dict | None, id_to_name: dict[int, str]) -> dict:
    """A per-provider mapping with the provider's name as key, unknown ids are left out."""
    named: dict = {}
    for key, value in (by_id or {}).items():
        try:
            pid = int(key)
        except (TypeError, ValueError):
            continue
        if pid in id_to_name:
            named[id_to_name[pid]] = value
    return named


def build_export(*, exported_from: str | None) -> dict:
    """Builds the export from the current state, providers as names instead of ids."""
    providers = db.list_providers()
    routes = db.list_routes()

    id_to_name = {p["id"]: p["name"] for p in providers}
    encrypt_keys = is_export_key_configured()

    exported_providers: list[dict] = []
    for p in providers:
        entry = {
            "name": p["name"],
            "protocol": p["protocol"],
            "base_url": p["base_url"],
            "capabilities": list(p.get("capabilities") or []),
            "voices": list(p.get("voices") or []),
            "enabled": bool(p.get("enabled", True)),
            "concurrency": dict(p.get("concurrency") or {}),
        }
        raw_key = p.get("api_key")
        if encrypt_keys and raw_key:
            entry["api_key"] = wrap_api_key(raw_key, provider_name=p["name"])
        exported_providers.append(entry)

    exported_routes: list[dict] = []
    for r in routes:
        exported_routes.append({
            "feature": r["feature"],
            "provider_name": id_to_name.get(r.get("provider_id")),
            "provider_order": [id_to_name[pid] for pid in (r.get("provider_order") or []) if pid in id_to_name],
            "model_name": r.get("model_name"),
            "user_choices": [id_to_name[pid] for pid in (r.get("user_choices") or []) if pid in id_to_name],
            "provider_models": _keyed_by_name(r.get("provider_models"), id_to_name),
            "provider_sampling": _keyed_by_name(r.get("provider_sampling"), id_to_name),
            "fallback_provider_name": id_to_name.get(r.get("fallback_provider_id")),
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "exported_from": exported_from,
        "api_keys_encrypted": encrypt_keys,
        "providers": exported_providers,
        "feature_routes": exported_routes,
    }


@router.get("/providers/export")
def export_config(
    _admin=Depends(_require),
):
    """Download the full AI config as JSON. Never includes api_keys."""
    payload = build_export(exported_from=None)
    filename = f"askfrancis-ai-config-{date.today().isoformat()}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _needs_api_key(protocol: str, base_url: str) -> bool:
    """Does this provider need an access key?"""
    if protocol == "deepl":
        return True
    if protocol == "openai_compat":
        lowered = base_url.lower()
        return not any(token in lowered for token in ("localhost", "127.0.0.1", "0.0.0.0"))
    return False  # docling and friends: no key needed


def validate_import_config(cfg: dict) -> None:
    """Validate an import payload before preview or commit. Raises 400."""
    if cfg.get("schema_version") != SCHEMA_VERSION:
        raise HTTPException(
            400,
            f"Unsupported schema_version {cfg.get('schema_version')!r} "
            f"(expected {SCHEMA_VERSION})",
        )

    bad_protocols = sorted({
        p["protocol"] for p in cfg.get("providers", [])
        if p.get("protocol") not in known_protocols()
    })
    if bad_protocols:
        raise HTTPException(400, f"Unknown protocols: {bad_protocols}")

    bad_caps: set[str] = set()
    for p in cfg.get("providers", []):
        for cap in p.get("capabilities", []):
            if cap not in CAPABILITIES:
                bad_caps.add(cap)
    if bad_caps:
        raise HTTPException(400, f"Unknown capabilities: {sorted(bad_caps)}")

    for p in cfg.get("providers", []):
        problem = _concurrency_problem(p.get("concurrency") or {})
        if problem:
            raise HTTPException(400, f"Invalid concurrency of provider {p.get('name')!r}: "
                                     f"{t(problem[0], 'en', **problem[1])}")

    bad_features = sorted({
        r["feature"] for r in cfg.get("feature_routes", [])
        if r.get("feature") not in FEATURES
    })
    if bad_features:
        raise HTTPException(400, f"Unknown features: {bad_features}")

    names = [p["name"] for p in cfg.get("providers", [])]
    if len(names) != len(set(names)):
        dups = sorted({n for n in names if names.count(n) > 1})
        raise HTTPException(400, f"Duplicate provider names in import: {dups}")


def build_import_preview(cfg: dict) -> dict:
    """Computes the difference between state and import, without writing."""
    validate_import_config(cfg)

    existing_by_name = {p["name"]: p for p in db.list_providers()}

    # Provider diffs.
    provider_diffs: list[dict] = []
    imported_names: set[str] = set()
    for p in cfg.get("providers", []):
        imported_names.add(p["name"])
        existing = existing_by_name.get(p["name"])
        action = "update" if existing else "create"
        protocol_change = None
        existing_has_key = False
        if existing:
            existing_has_key = bool(existing.get("api_key"))
            if existing["protocol"] != p["protocol"]:
                protocol_change = {
                    "from": existing["protocol"], "to": p["protocol"],
                }
        envelope = p.get("api_key")
        encrypted_key_present = is_envelope(envelope)
        encrypted_key_recoverable = (
            encrypted_key_present
            and try_unwrap_api_key(envelope, provider_name=p["name"]) is not None
        )
        provider_diffs.append({
            "name": p["name"],
            "action": action,
            "needs_api_key": _needs_api_key(p["protocol"], p["base_url"]),
            "existing_has_key": existing_has_key,
            "protocol_change": protocol_change,
            "encrypted_key_present": encrypted_key_present,
            "encrypted_key_recoverable": encrypted_key_recoverable,
        })

    # A route's provider must exist after the merge.
    available_names = set(existing_by_name.keys()) | imported_names

    route_diffs: list[dict] = []
    for r in cfg.get("feature_routes", []):
        pname = r.get("provider_name")
        # A voice route with only a fallback is imported on that fallback alone.
        if pname is None and r["feature"] == "tts" and r.get("fallback_provider_name") in available_names:
            pname = r["fallback_provider_name"]
        if pname is None:
            route_diffs.append({
                "feature": r["feature"], "action": "skip_unresolved",
                "reason": "Keine Provider-Zuordnung im Export",
            })
            continue
        if pname not in available_names:
            route_diffs.append({
                "feature": r["feature"], "action": "skip_unresolved",
                "reason": f"Provider '{pname}' nicht im Import enthalten",
            })
            continue
        # The existing route decides whether this creates or updates.
        action = "update" if db.get_route(r["feature"]) is not None else "create"
        route_diffs.append({
            "feature": r["feature"], "action": action,
            "resolved_provider": pname,
        })

    return {"providers": provider_diffs, "routes": route_diffs}


@router.post("/providers/import/preview")
def import_preview(
    body: ImportConfigRequest,
    _admin=Depends(_require),
):
    return build_import_preview(body.config.model_dump())


def perform_import(cfg: dict, *, probe_ids: list[int] | None = None) -> dict:
    """Applies an import without deleting existing rows or overwriting keys, probes are queued in probe_ids when given."""
    validate_import_config(cfg)
    providers = _import_providers(cfg, probe_ids)
    return {**providers, **_import_routes(cfg)}


def _import_providers(cfg: dict, probe_ids: list[int] | None) -> dict:
    """Creates or updates the providers of an import and says which ones still lack a key."""
    existing_by_name = {p["name"]: p for p in db.list_providers()}
    providers_created = 0
    providers_updated = 0
    providers_needing_key: list[str] = []

    for p in cfg.get("providers", []):
        existing = existing_by_name.get(p["name"])
        capabilities = [c for c in p.get("capabilities", []) if c in CAPABILITIES]
        voices = list(p.get("voices") or [])
        envelope = p.get("api_key")
        recovered_key = (
            try_unwrap_api_key(envelope, provider_name=p["name"])
            if is_envelope(envelope)
            else None
        )
        concurrency = p.get("concurrency")
        if concurrency is not None:
            concurrency = {k: v for k, v in concurrency.items() if v is not None}
        if existing is None:
            row = db.create_provider(
                name=p["name"], protocol=p["protocol"],
                base_url=p["base_url"], api_key=recovered_key,
                capabilities=capabilities, voices=voices,
                enabled=bool(p.get("enabled", True)),
                concurrency=concurrency or {},
            )
            providers_created += 1
        else:
            # Only set the key when the row has none.
            update_kwargs: dict = {
                "protocol": p["protocol"], "base_url": p["base_url"],
                "capabilities": capabilities, "voices": voices,
                "enabled": bool(p.get("enabled", True)),
            }
            if recovered_key and not existing.get("api_key"):
                update_kwargs["api_key"] = recovered_key
            # An export from before the caps leaves the existing caps alone.
            if concurrency is not None:
                update_kwargs["concurrency"] = concurrency
            row = db.update_provider(existing["id"], **update_kwargs)
            providers_updated += 1
        # Re-probe so probe_status reflects current reachability.
        if probe_ids is None:
            probe_provider(row["id"])
        else:
            probe_ids.append(row["id"])
        # The key is only set on creation or when backfilling.
        if _needs_api_key(p["protocol"], p["base_url"]) and not row.get("api_key"):
            providers_needing_key.append(p["name"])

    return {
        "providers_created": providers_created,
        "providers_updated": providers_updated,
        "providers_needing_key": providers_needing_key,
    }


def _import_routes(cfg: dict) -> dict:
    """Sets the routes of an import on the providers as they now stand, by name."""
    name_to_id = {p["name"]: p["id"] for p in db.list_providers()}
    existing_routes = {r["feature"]: r for r in db.list_routes()}
    routes_created = 0
    routes_updated = 0
    routes_skipped = 0
    embedding_changed = False

    for r in cfg.get("feature_routes", []):
        pname = r.get("provider_name")
        voice = r["feature"] == "tts"
        fallback_id = name_to_id.get(r.get("fallback_provider_name"))
        # A voice route may stand on its fallback alone, every other route needs its first choice.
        standalone = voice and pname is None and fallback_id is not None
        if not standalone and pname not in name_to_id:
            routes_skipped += 1
            continue
        pid = name_to_id.get(pname)
        user_choice_ids = [
            name_to_id[n] for n in (r.get("user_choices") or [])
            if n in name_to_id
        ]
        provider_models: dict[str, str] = {}
        for n, model in (r.get("provider_models") or {}).items():
            if n in name_to_id:
                provider_models[str(name_to_id[n])] = model
        provider_sampling: dict[str, dict] = {}
        for n, werte in (r.get("provider_sampling") or {}).items():
            if n in name_to_id and isinstance(werte, dict):
                provider_sampling[str(name_to_id[n])] = werte
        # An unknown fallback name is dropped, and outside voice so is one equal to the first choice.
        if fallback_id == pid and not voice:
            fallback_id = None

        db.set_route(
            r["feature"],
            provider_id=pid,
            model_name=r.get("model_name"),
            user_choices=user_choice_ids,
            provider_models=provider_models,
            provider_sampling=provider_sampling,
            fallback_provider_id=fallback_id,
            provider_order=[name_to_id[n] for n in (r.get("provider_order") or []) if n in name_to_id],
        )
        if r["feature"] in existing_routes:
            routes_updated += 1
        else:
            routes_created += 1
        if r["feature"] == "embedding":
            embedding_changed = True

    if embedding_changed:
        # Imported here so a test can replace it at its source.
        from src.routes.admin._embedding import invalidate_fingerprint_cache
        invalidate_fingerprint_cache()

    return {
        "routes_created": routes_created,
        "routes_updated": routes_updated,
        "routes_skipped": routes_skipped,
    }


def _probe_all(provider_ids: list[int]) -> None:
    """Probes one provider after the other, one failure never stops the rest."""
    for pid in provider_ids:
        try:
            probe_provider(pid)
        except Exception:  # noqa: BLE001 - background task must not die on one provider
            logger.exception("background probe failed for provider id={}", pid)


@router.post("/providers/import")
def import_config(
    body: ImportConfigRequest,
    background: BackgroundTasks,
    _admin=Depends(_require),
):
    # Probing every provider can outlast the proxy timeout, so it runs after the response.
    probe_ids: list[int] = []
    result = perform_import(body.config.model_dump(), probe_ids=probe_ids)
    background.add_task(_probe_all, probe_ids)
    return result


def perform_clear_all() -> dict:
    """Wipe all providers + feature_routes. Destructive."""
    routes_deleted = db.delete_all_routes()
    providers_deleted = db.delete_all_providers()

    from src.routes.admin._embedding import invalidate_fingerprint_cache
    invalidate_fingerprint_cache()

    return {
        "providers_deleted": providers_deleted,
        "routes_deleted": routes_deleted,
    }


@router.delete("/providers/all")
def clear_all(_admin=Depends(_require)):
    return perform_clear_all()
