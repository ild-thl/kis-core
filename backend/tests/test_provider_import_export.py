"""Checks export and import of the provider settings."""
from unittest.mock import MagicMock


def _make_provider(id, name, *, protocol="openai_compat", api_key=None,
                   base_url="http://example.com", capabilities=None,
                   voices=None, enabled=True):
    return {
        "id": id, "name": name, "protocol": protocol, "api_key": api_key,
        "base_url": base_url, "enabled": enabled,
        "capabilities": capabilities or [],
        "voices": voices or [],
    }


def _make_route(feature, provider_id=None, model_name=None,
                user_choices=None, provider_models=None):
    return {
        "feature": feature, "provider_id": provider_id,
        "model_name": model_name,
        "user_choices": user_choices or [],
        "provider_models": provider_models or {},
    }


def test_export_empty_db_returns_empty_arrays(monkeypatch):
    from src.routes.admin.providers import build_export

    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [])
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])

    result = build_export(exported_from=None)
    assert result["schema_version"] == 1
    assert result["providers"] == []
    assert result["feature_routes"] == []
    assert "exported_at" in result


def test_export_omits_api_key_when_export_key_unset(monkeypatch):
    """No ASKF_SECRETS_KEY → export drops api_key entirely (legacy behavior)."""
    from src.routes.admin.providers import build_export

    monkeypatch.delenv("ASKF_SECRETS_KEY", raising=False)
    monkeypatch.setattr(
        "src.routes.admin.providers.db.list_providers",
        lambda: [_make_provider(1, "Anbieter A", api_key="sk-secret",
                                capabilities=["chat"])],
    )
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])

    result = build_export(exported_from=None)
    assert result["api_keys_encrypted"] is False
    p = result["providers"][0]
    assert "api_key" not in p
    assert "id" not in p
    assert p["name"] == "Anbieter A"
    assert p["capabilities"] == ["chat"]


def test_export_wraps_api_key_when_export_key_set(monkeypatch):
    """ASKF_SECRETS_KEY set → api_key is included as AES-GCM envelope."""
    from src.routes.admin.providers import build_export
    from src.services.export_crypto import try_unwrap_api_key

    monkeypatch.setenv("ASKF_SECRETS_KEY", "test-secret-xyz")
    monkeypatch.setattr(
        "src.routes.admin.providers.db.list_providers",
        lambda: [_make_provider(1, "Anbieter A", api_key="sk-secret")],
    )
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])

    result = build_export(exported_from=None)
    assert result["api_keys_encrypted"] is True
    p = result["providers"][0]
    env = p["api_key"]
    assert env["alg"] == "aesgcm-v2"
    assert try_unwrap_api_key(env, provider_name="Anbieter A") == "sk-secret"


def test_export_envelope_rejects_provider_name_swap(monkeypatch):
    """An envelope is bound to its provider name."""
    from src.services.export_crypto import (
        try_unwrap_api_key, wrap_api_key,
    )

    monkeypatch.setenv("ASKF_SECRETS_KEY", "test-secret-xyz")
    env = wrap_api_key("sk-secret", provider_name="Anbieter A")
    assert try_unwrap_api_key(env, provider_name="Anbieter A") == "sk-secret"
    assert try_unwrap_api_key(env, provider_name="Evil") is None


def test_export_v1_envelope_still_decryptable(monkeypatch):
    """Old envelopes without a binding have to stay readable."""
    import os
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from src.services.export_crypto import _derive_key, _b64e, try_unwrap_api_key

    monkeypatch.setenv("ASKF_SECRETS_KEY", "test-secret-xyz")
    key = _derive_key("test-secret-xyz")
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, b"sk-legacy", None)
    legacy_env = {"alg": "aesgcm-v1", "nonce": _b64e(nonce), "ct": _b64e(ct)}
    assert try_unwrap_api_key(legacy_env, provider_name="Whatever") == "sk-legacy"


def test_export_skips_envelope_for_providers_without_key(monkeypatch):
    from src.routes.admin.providers import build_export

    monkeypatch.setenv("ASKF_SECRETS_KEY", "test-secret-xyz")
    monkeypatch.setattr(
        "src.routes.admin.providers.db.list_providers",
        lambda: [_make_provider(1, "Stimmen lokal", api_key=None)],
    )
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])

    result = build_export(exported_from=None)
    assert "api_key" not in result["providers"][0]


def test_export_translates_route_ids_to_provider_names(monkeypatch):
    from src.routes.admin.providers import build_export

    providers = [
        _make_provider(1, "Anbieter A"),
        _make_provider(2, "DeepL DE-EN", protocol="deepl"),
    ]
    routes = [
        _make_route("chat", provider_id=1, model_name="mistral-large"),
        _make_route("doc_translate", provider_id=2,
                    user_choices=[1, 2],
                    provider_models={"1": "mistral-small", "2": ""}),
    ]
    monkeypatch.setattr(
        "src.routes.admin.providers.db.list_providers", lambda: providers
    )
    monkeypatch.setattr(
        "src.routes.admin.providers.db.list_routes", lambda: routes
    )

    result = build_export(exported_from=None)
    chat = next(r for r in result["feature_routes"] if r["feature"] == "chat")
    assert chat["provider_name"] == "Anbieter A"
    assert chat["model_name"] == "mistral-large"

    tr = next(r for r in result["feature_routes"]
              if r["feature"] == "doc_translate")
    assert tr["provider_name"] == "DeepL DE-EN"
    assert sorted(tr["user_choices"]) == sorted(["Anbieter A", "DeepL DE-EN"])
    assert tr["provider_models"] == {
        "Anbieter A": "mistral-small", "DeepL DE-EN": ""
    }


def test_export_drops_routes_with_missing_provider_id(monkeypatch):
    """An orphaned route must not crash the export."""
    from src.routes.admin.providers import build_export

    monkeypatch.setattr(
        "src.routes.admin.providers.db.list_providers",
        lambda: [_make_provider(1, "Anbieter A")],
    )
    monkeypatch.setattr(
        "src.routes.admin.providers.db.list_routes",
        lambda: [_make_route("chat", provider_id=999, model_name="x")],
    )

    result = build_export(exported_from=None)
    chat = next(r for r in result["feature_routes"] if r["feature"] == "chat")
    assert chat["provider_name"] is None


# ─── Import preview ────────────────────────────────────────────────────────


def _valid_config(providers=None, routes=None):
    return {
        "schema_version": 1,
        "exported_at": "2026-05-28T12:00:00Z",
        "exported_from": "https://test.example",
        "providers": providers or [],
        "feature_routes": routes or [],
    }


def _exported_provider(name, *, protocol="openai_compat",
                       base_url="https://example.com",
                       capabilities=None, voices=None, enabled=True):
    return {
        "name": name, "protocol": protocol, "base_url": base_url,
        "capabilities": capabilities or [], "voices": voices or [],
        "enabled": enabled,
    }


def _exported_route(feature, provider_name=None, model_name=None,
                    user_choices=None, provider_models=None):
    return {
        "feature": feature, "provider_name": provider_name,
        "model_name": model_name,
        "user_choices": user_choices or [],
        "provider_models": provider_models or {},
    }


def test_preview_new_provider_action_create(monkeypatch):
    from src.routes.admin.providers import build_import_preview

    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [])
    cfg = _valid_config(providers=[_exported_provider("Anbieter A")])

    result = build_import_preview(cfg)
    assert len(result["providers"]) == 1
    p = result["providers"][0]
    assert p["name"] == "Anbieter A"
    assert p["action"] == "create"
    assert p["needs_api_key"] is True  # remote openai_compat
    assert p["existing_has_key"] is False
    assert p["protocol_change"] is None


def test_preview_existing_provider_action_update_preserves_key_flag(monkeypatch):
    from src.routes.admin.providers import build_import_preview

    existing = _make_provider(1, "Anbieter A", api_key="sk-existing")
    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [existing])
    cfg = _valid_config(providers=[_exported_provider("Anbieter A")])

    result = build_import_preview(cfg)
    p = result["providers"][0]
    assert p["action"] == "update"
    assert p["existing_has_key"] is True


def test_preview_protocol_change_detected(monkeypatch):
    from src.routes.admin.providers import build_import_preview

    existing = _make_provider(1, "AltProvider", protocol="openai_compat")
    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [existing])
    cfg = _valid_config(providers=[
        _exported_provider("AltProvider", protocol="deepl")
    ])

    result = build_import_preview(cfg)
    p = result["providers"][0]
    assert p["protocol_change"] == {"from": "openai_compat", "to": "deepl"}


def test_preview_needs_api_key_false_for_localhost(monkeypatch):
    from src.routes.admin.providers import build_import_preview

    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [])
    cfg = _valid_config(providers=[
        _exported_provider("Stimmen lokal",
                           base_url="http://localhost:9000/v1"),
    ])

    result = build_import_preview(cfg)
    p = result["providers"][0]
    assert p["needs_api_key"] is False


def test_preview_route_with_unknown_provider_skipped(monkeypatch):
    from src.routes.admin.providers import build_import_preview

    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [])
    monkeypatch.setattr("src.routes.admin.providers.db.get_route",
                        lambda f: None)
    cfg = _valid_config(
        providers=[_exported_provider("Anbieter A")],
        routes=[
            _exported_route("chat", provider_name="Anbieter A",
                            model_name="m1"),
            _exported_route("doc_translate", provider_name="GhostProvider"),
        ],
    )

    result = build_import_preview(cfg)
    routes_by_feature = {r["feature"]: r for r in result["routes"]}
    assert routes_by_feature["chat"]["action"] == "create"
    assert routes_by_feature["chat"]["resolved_provider"] == "Anbieter A"
    assert routes_by_feature["doc_translate"]["action"] == "skip_unresolved"
    assert "GhostProvider" in routes_by_feature["doc_translate"]["reason"]


def test_preview_does_not_modify_db(monkeypatch):
    """Preview must be a pure read — verify no mutating DB calls happen."""
    from src.routes.admin.providers import build_import_preview

    create_mock = MagicMock()
    update_mock = MagicMock()
    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [])
    monkeypatch.setattr("src.routes.admin.providers.db.create_provider",
                        create_mock)
    monkeypatch.setattr("src.routes.admin.providers.db.update_provider",
                        update_mock)

    cfg = _valid_config(providers=[_exported_provider("Anbieter A")])
    build_import_preview(cfg)

    create_mock.assert_not_called()
    update_mock.assert_not_called()


def test_validate_rejects_unknown_schema_version():
    from src.routes.admin.providers import validate_import_config
    import pytest
    from fastapi import HTTPException

    cfg = {"schema_version": 99, "exported_at": "x", "providers": [],
           "feature_routes": []}
    with pytest.raises(HTTPException) as exc:
        validate_import_config(cfg)
    assert exc.value.status_code == 400
    assert "schema" in exc.value.detail.lower() or "version" in exc.value.detail.lower()


def test_validate_rejects_unknown_protocol():
    from src.routes.admin.providers import validate_import_config
    import pytest
    from fastapi import HTTPException

    cfg = _valid_config(providers=[
        _exported_provider("X", protocol="nonsense_protocol")
    ])
    with pytest.raises(HTTPException) as exc:
        validate_import_config(cfg)
    assert exc.value.status_code == 400


def test_validate_rejects_unknown_capability():
    from src.routes.admin.providers import validate_import_config
    import pytest
    from fastapi import HTTPException

    cfg = _valid_config(providers=[
        _exported_provider("X", capabilities=["nonsense_capability"])
    ])
    with pytest.raises(HTTPException) as exc:
        validate_import_config(cfg)
    assert exc.value.status_code == 400


def test_validate_rejects_unknown_feature():
    from src.routes.admin.providers import validate_import_config
    import pytest
    from fastapi import HTTPException

    cfg = _valid_config(routes=[_exported_route("nonsense_feature")])
    with pytest.raises(HTTPException) as exc:
        validate_import_config(cfg)
    assert exc.value.status_code == 400


def test_validate_rejects_duplicate_provider_names():
    from src.routes.admin.providers import validate_import_config
    import pytest
    from fastapi import HTTPException

    cfg = _valid_config(providers=[
        _exported_provider("A"), _exported_provider("A"),
    ])
    with pytest.raises(HTTPException) as exc:
        validate_import_config(cfg)
    assert exc.value.status_code == 400


# ─── Import commit ─────────────────────────────────────────────────────────


def test_import_creates_new_provider_without_api_key(monkeypatch):
    from src.routes.admin.providers import perform_import

    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [])
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])
    create_mock = MagicMock(return_value=_make_provider(10, "Anbieter A"))
    monkeypatch.setattr("src.routes.admin.providers.db.create_provider",
                        create_mock)
    monkeypatch.setattr("src.routes.admin.provider_transfer.probe_provider",
                        lambda pid, **kw: None)

    cfg = _valid_config(providers=[_exported_provider("Anbieter A")])
    result = perform_import(cfg)

    create_mock.assert_called_once()
    kwargs = create_mock.call_args.kwargs
    assert kwargs["api_key"] is None  # never carries a key in
    assert kwargs["name"] == "Anbieter A"
    assert result["providers_created"] == 1
    assert result["providers_updated"] == 0


def test_import_decrypts_envelope_and_sets_key_on_create(monkeypatch):
    """Envelope present + matching ASKF_SECRETS_KEY → recovered key reaches DB."""
    from src.routes.admin.providers import perform_import
    from src.services.export_crypto import wrap_api_key

    monkeypatch.setenv("ASKF_SECRETS_KEY", "roundtrip-secret")
    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [])
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])
    create_mock = MagicMock(return_value=_make_provider(10, "Anbieter A",
                                                       api_key="sk-real"))
    monkeypatch.setattr("src.routes.admin.providers.db.create_provider",
                        create_mock)
    monkeypatch.setattr("src.routes.admin.provider_transfer.probe_provider",
                        lambda pid, **kw: None)

    provider = _exported_provider("Anbieter A")
    provider["api_key"] = wrap_api_key("sk-real", provider_name="Anbieter A")
    cfg = _valid_config(providers=[provider])
    perform_import(cfg)

    assert create_mock.call_args.kwargs["api_key"] == "sk-real"


def test_import_ignores_envelope_with_wrong_secret(monkeypatch):
    """A foreign key leaves the provider without an access key."""
    from src.routes.admin.providers import perform_import
    from src.services.export_crypto import wrap_api_key

    monkeypatch.setenv("ASKF_SECRETS_KEY", "secret-A")
    envelope = wrap_api_key("sk-real", provider_name="Anbieter A")
    monkeypatch.setenv("ASKF_SECRETS_KEY", "secret-B")

    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [])
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])
    create_mock = MagicMock(return_value=_make_provider(
        1, "Anbieter A", base_url="https://api.example", api_key=None,
    ))
    monkeypatch.setattr("src.routes.admin.providers.db.create_provider",
                        create_mock)
    monkeypatch.setattr("src.routes.admin.provider_transfer.probe_provider",
                        lambda pid, **kw: None)

    provider = _exported_provider("Anbieter A", base_url="https://api.example")
    provider["api_key"] = envelope
    cfg = _valid_config(providers=[provider])
    result = perform_import(cfg)

    assert create_mock.call_args.kwargs["api_key"] is None
    assert "Anbieter A" in result["providers_needing_key"]


def test_import_does_not_overwrite_existing_key_with_envelope(monkeypatch):
    """An existing key wins against the one from the import."""
    from src.routes.admin.providers import perform_import
    from src.services.export_crypto import wrap_api_key

    monkeypatch.setenv("ASKF_SECRETS_KEY", "same-secret")
    existing = _make_provider(1, "Anbieter A", api_key="sk-existing")
    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [existing])
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])
    update_mock = MagicMock(return_value=existing)
    monkeypatch.setattr("src.routes.admin.providers.db.update_provider",
                        update_mock)
    monkeypatch.setattr("src.routes.admin.provider_transfer.probe_provider",
                        lambda pid, **kw: None)

    provider = _exported_provider("Anbieter A")
    provider["api_key"] = wrap_api_key("sk-from-backup", provider_name="Anbieter A")
    perform_import(_valid_config(providers=[provider]))

    assert "api_key" not in update_mock.call_args.kwargs


def test_import_restores_key_into_empty_existing_row(monkeypatch):
    """Provider exists locally without a key → envelope unwraps and fills it."""
    from src.routes.admin.providers import perform_import
    from src.services.export_crypto import wrap_api_key

    monkeypatch.setenv("ASKF_SECRETS_KEY", "same-secret")
    existing = _make_provider(1, "Anbieter A", api_key=None)
    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [existing])
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])
    update_mock = MagicMock(return_value=_make_provider(
        1, "Anbieter A", api_key="sk-from-backup",
    ))
    monkeypatch.setattr("src.routes.admin.providers.db.update_provider",
                        update_mock)
    monkeypatch.setattr("src.routes.admin.provider_transfer.probe_provider",
                        lambda pid, **kw: None)

    provider = _exported_provider("Anbieter A")
    provider["api_key"] = wrap_api_key("sk-from-backup", provider_name="Anbieter A")
    perform_import(_valid_config(providers=[provider]))

    assert update_mock.call_args.kwargs["api_key"] == "sk-from-backup"


def test_import_update_preserves_existing_api_key(monkeypatch):
    from src.routes.admin.providers import perform_import

    existing = _make_provider(1, "Anbieter A", api_key="sk-existing")
    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [existing])
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])
    update_mock = MagicMock(return_value=existing)
    monkeypatch.setattr("src.routes.admin.providers.db.update_provider",
                        update_mock)
    monkeypatch.setattr("src.routes.admin.provider_transfer.probe_provider",
                        lambda pid, **kw: None)

    cfg = _valid_config(providers=[_exported_provider("Anbieter A")])
    perform_import(cfg)

    update_mock.assert_called_once()
    kwargs = update_mock.call_args.kwargs
    assert "api_key" not in kwargs  # never touches the key on update


def test_import_creates_route_resolving_provider_names(monkeypatch):
    from src.routes.admin.providers import perform_import

    created = _make_provider(42, "Anbieter A")
    list_calls = {"n": 0}

    def fake_list_providers():
        list_calls["n"] += 1
        return [] if list_calls["n"] == 1 else [created]

    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        fake_list_providers)
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])
    monkeypatch.setattr("src.routes.admin.providers.db.create_provider",
                        lambda **kw: created)
    monkeypatch.setattr("src.routes.admin.provider_transfer.probe_provider",
                        lambda pid, **kw: None)

    set_route_mock = MagicMock()
    monkeypatch.setattr("src.routes.admin.providers.db.set_route",
                        set_route_mock)

    cfg = _valid_config(
        providers=[_exported_provider("Anbieter A")],
        routes=[_exported_route("chat", provider_name="Anbieter A",
                                model_name="mistral")],
    )
    result = perform_import(cfg)

    set_route_mock.assert_called_once()
    kwargs = set_route_mock.call_args.kwargs
    assert kwargs["provider_id"] == 42
    assert kwargs["model_name"] == "mistral"
    assert result["routes_created"] + result["routes_updated"] == 1


def test_import_skips_route_with_unresolved_provider(monkeypatch):
    from src.routes.admin.providers import perform_import

    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [])
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])
    set_route_mock = MagicMock()
    monkeypatch.setattr("src.routes.admin.providers.db.set_route",
                        set_route_mock)

    cfg = _valid_config(
        routes=[_exported_route("chat", provider_name="Missing")],
    )
    result = perform_import(cfg)

    set_route_mock.assert_not_called()
    assert result["routes_skipped"] == 1


def test_import_filters_unresolved_user_choices(monkeypatch):
    """Unresolvable names are dropped, the route is set anyway."""
    from src.routes.admin.providers import perform_import

    p = _make_provider(7, "Anbieter A")
    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [p])
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])
    monkeypatch.setattr("src.routes.admin.provider_transfer.probe_provider",
                        lambda pid, **kw: None)
    monkeypatch.setattr("src.routes.admin.providers.db.update_provider",
                        lambda *a, **kw: p)

    set_route_mock = MagicMock()
    monkeypatch.setattr("src.routes.admin.providers.db.set_route",
                        set_route_mock)

    cfg = _valid_config(
        providers=[_exported_provider("Anbieter A")],
        routes=[
            _exported_route(
                "tts",
                provider_name="Anbieter A",
                user_choices=["Anbieter A", "Ghost"],
                provider_models={"Anbieter A": "m1", "Ghost": "m2"},
            ),
        ],
    )
    perform_import(cfg)

    kwargs = set_route_mock.call_args.kwargs
    assert kwargs["user_choices"] == [7]
    assert kwargs["provider_models"] == {"7": "m1"}


def test_import_triggers_reprobe_for_each_provider(monkeypatch):
    from src.routes.admin.providers import perform_import

    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [])
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])
    monkeypatch.setattr(
        "src.routes.admin.providers.db.create_provider",
        lambda **kw: _make_provider(99, kw["name"]),
    )
    probe_mock = MagicMock()
    monkeypatch.setattr("src.routes.admin.provider_transfer.probe_provider",
                        probe_mock)

    cfg = _valid_config(providers=[
        _exported_provider("A"), _exported_provider("B"),
    ])
    perform_import(cfg)

    assert probe_mock.call_count == 2


def test_import_invalidates_fingerprint_cache_when_embedding_route_set(monkeypatch):
    from src.routes.admin.providers import perform_import

    p = _make_provider(5, "EmbedProvider")
    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [p])
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])
    monkeypatch.setattr("src.routes.admin.providers.db.set_route",
                        lambda *a, **kw: None)
    monkeypatch.setattr("src.routes.admin.provider_transfer.probe_provider",
                        lambda pid, **kw: None)
    monkeypatch.setattr("src.routes.admin.providers.db.update_provider",
                        lambda *a, **kw: p)

    invalidate_mock = MagicMock()
    monkeypatch.setattr(
        "src.routes.admin._embedding.invalidate_fingerprint_cache",
        invalidate_mock,
    )

    cfg = _valid_config(
        providers=[_exported_provider("EmbedProvider")],
        routes=[_exported_route("embedding", provider_name="EmbedProvider", model_name="emb")],
    )
    perform_import(cfg)

    invalidate_mock.assert_called_once()


def test_import_response_lists_providers_needing_key(monkeypatch):
    from src.routes.admin.providers import perform_import

    monkeypatch.setattr("src.routes.admin.providers.db.list_providers",
                        lambda: [])
    monkeypatch.setattr("src.routes.admin.providers.db.list_routes",
                        lambda: [])
    monkeypatch.setattr(
        "src.routes.admin.providers.db.create_provider",
        lambda **kw: _make_provider(1, kw["name"], protocol=kw["protocol"],
                                    base_url=kw["base_url"]),
    )
    monkeypatch.setattr("src.routes.admin.provider_transfer.probe_provider",
                        lambda pid, **kw: None)

    cfg = _valid_config(providers=[
        _exported_provider("Anbieter A",
                           base_url="https://llm.example.de"),
        _exported_provider("Stimmen lokal",
                           base_url="http://localhost:9000/v1"),
    ])
    result = perform_import(cfg)

    assert "Anbieter A" in result["providers_needing_key"]
    assert "Stimmen lokal" not in result["providers_needing_key"]


# ─── Clear all ─────────────────────────────────────────────────────────────


def test_clear_all_deletes_providers_and_routes(monkeypatch):
    from src.routes.admin.providers import perform_clear_all

    del_providers = MagicMock(return_value=3)
    del_routes = MagicMock(return_value=5)
    monkeypatch.setattr("src.routes.admin.providers.db.delete_all_providers",
                        del_providers)
    monkeypatch.setattr("src.routes.admin.providers.db.delete_all_routes",
                        del_routes)
    monkeypatch.setattr(
        "src.routes.admin._embedding.invalidate_fingerprint_cache",
        MagicMock(),
    )

    result = perform_clear_all()
    del_providers.assert_called_once()
    del_routes.assert_called_once()
    assert result == {"providers_deleted": 3, "routes_deleted": 5}


def test_clear_all_invalidates_fingerprint_cache(monkeypatch):
    from src.routes.admin.providers import perform_clear_all

    monkeypatch.setattr("src.routes.admin.providers.db.delete_all_providers",
                        lambda: 0)
    monkeypatch.setattr("src.routes.admin.providers.db.delete_all_routes",
                        lambda: 0)
    invalidate_mock = MagicMock()
    monkeypatch.setattr(
        "src.routes.admin._embedding.invalidate_fingerprint_cache",
        invalidate_mock,
    )

    perform_clear_all()
    invalidate_mock.assert_called_once()


def test_clear_all_routes_deleted_before_providers(monkeypatch):
    """The routes go first, that is the safe order."""
    from src.routes.admin.providers import perform_clear_all

    call_order: list[str] = []
    monkeypatch.setattr(
        "src.routes.admin.providers.db.delete_all_routes",
        lambda: call_order.append("routes") or 0,
    )
    monkeypatch.setattr(
        "src.routes.admin.providers.db.delete_all_providers",
        lambda: call_order.append("providers") or 0,
    )
    monkeypatch.setattr(
        "src.routes.admin._embedding.invalidate_fingerprint_cache",
        MagicMock(),
    )

    perform_clear_all()
    assert call_order == ["routes", "providers"]
