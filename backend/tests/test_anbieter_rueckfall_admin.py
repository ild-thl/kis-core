"""Checks the admin side of the provider fallback and of the concurrency caps."""

import os
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.features.ai_providers.repository.feature_routes import FEATURES
from src.routes.admin import feature_routes, provider_transfer, providers as admin
from src.routes.admin._models import (
    CreateProviderRequest,
    ExportedConfig,
    SetFeatureRouteRequest,
    UpdateProviderRequest,
)


def _provider(pid, name=None, *, protocol="openai_compat", caps=("chat",), enabled=True,
              concurrency=None, voices=()):
    return {
        "id": pid, "name": name or f"P{pid}", "protocol": protocol,
        "base_url": f"http://p{pid}", "api_key": None, "enabled": enabled,
        "capabilities": list(caps), "voices": list(voices), "concurrency": concurrency or {},
    }


_STIMMEN = ({"voice_id": "anna", "name": "Anna", "language": "de"},)


# ─── Meta ────────────────────────────────────────────────────────────────────


def test_meta_lists_the_buckets_and_the_fallback_features(monkeypatch):
    meta = admin.get_provider_meta(_admin=None)
    assert meta["concurrency_buckets"] == ["llm", "stt", "tts", "image", "embedding", "ocr"]
    assert meta["fallback_features"] == list(FEATURES)


# ─── Concurrency on the provider ─────────────────────────────────────────────


@pytest.fixture
def patch_env(monkeypatch):
    """A provider 1 that the PATCH route can load, the update is recorded."""
    monkeypatch.setattr(admin.db, "get_provider", lambda pid: _provider(1) if pid == 1 else None)
    monkeypatch.setattr(admin.db, "get_provider_by_name", lambda name: None)
    update = MagicMock(side_effect=lambda pid, **kw: {**_provider(1), **kw})
    monkeypatch.setattr(admin.db, "update_provider", update)
    monkeypatch.setattr(admin, "probe_provider", lambda *a, **kw: None)
    # Switching a provider off re-derives every route, the real ones must stay out of it.
    monkeypatch.setattr(admin.db, "list_routes", lambda: [])
    monkeypatch.setattr(admin.db, "set_route", MagicMock())
    return update


def _patch(body, locale="de"):
    return admin.update_provider(1, UpdateProviderRequest(**body), _admin=None, locale=locale)


def test_patch_stores_the_concurrency(patch_env):
    result = _patch({"concurrency": {"llm": 10, "tts": 4}})
    assert patch_env.call_args.kwargs["concurrency"] == {"llm": 10, "tts": 4}
    assert result["provider"]["concurrency"] == {"llm": 10, "tts": 4}


def test_patch_with_an_empty_object_clears_every_cap(patch_env):
    _patch({"concurrency": {}})
    assert patch_env.call_args.kwargs["concurrency"] == {}


def test_patch_without_the_field_leaves_the_caps_alone(patch_env):
    _patch({"enabled": False})
    assert "concurrency" not in patch_env.call_args.kwargs


@pytest.mark.parametrize("wert", [1, 1000])
def test_patch_accepts_the_bounds(patch_env, wert):
    _patch({"concurrency": {"image": wert}})
    assert patch_env.call_args.kwargs["concurrency"] == {"image": wert}


def test_patch_rejects_an_unknown_bucket(patch_env):
    with pytest.raises(HTTPException) as exc:
        _patch({"concurrency": {"gpu": 2}})
    assert exc.value.status_code == 422
    assert "gpu" in exc.value.detail
    assert "admin.providers" not in exc.value.detail
    patch_env.assert_not_called()


@pytest.mark.parametrize("wert", [0, -1, 1001, "5", 2.5, True])
def test_patch_rejects_values_outside_whole_numbers_1_to_1000(patch_env, wert):
    with pytest.raises(HTTPException) as exc:
        _patch({"concurrency": {"llm": wert}})
    assert exc.value.status_code == 422
    assert "admin.providers" not in exc.value.detail
    patch_env.assert_not_called()


def test_the_messages_exist_in_english_too(patch_env):
    with pytest.raises(HTTPException) as de:
        _patch({"concurrency": {"llm": 0}}, locale="de")
    with pytest.raises(HTTPException) as en:
        _patch({"concurrency": {"llm": 0}}, locale="en")
    assert de.value.detail != en.value.detail
    assert "admin.providers" not in en.value.detail


@pytest.fixture
def create_env(monkeypatch):
    """Creating a provider without a real database or probe."""
    create = MagicMock(side_effect=lambda **kw: {**_provider(7), **kw, "id": 7})
    monkeypatch.setattr(admin.db, "get_provider_by_name", lambda name: None)
    monkeypatch.setattr(admin.db, "create_provider", create)
    monkeypatch.setattr(admin.db, "get_provider", lambda pid: _provider(7))
    monkeypatch.setattr(admin, "probe_provider", lambda *a, **kw: None)
    return create


def _create(**extra):
    body = CreateProviderRequest(name="Lokal", protocol="openai_compat",
                                 base_url="http://lokal", **extra)
    return admin.create_provider(body, _admin=None, locale="de")


def test_create_stores_the_concurrency(create_env):
    _create(concurrency={"llm": 10})
    assert create_env.call_args.kwargs["concurrency"] == {"llm": 10}


def test_create_without_the_field_stores_no_caps(create_env):
    _create()
    assert create_env.call_args.kwargs["concurrency"] == {}


def test_create_rejects_an_invalid_cap(create_env):
    with pytest.raises(HTTPException) as exc:
        _create(concurrency={"llm": 0})
    assert exc.value.status_code == 422
    create_env.assert_not_called()


# ─── Fallback on the feature route ───────────────────────────────────────────


_PROVIDERS = {
    1: _provider(1, caps=("chat", "embedding", "vision", "ocr", "stt", "image_gen",
                          "image_edit")),
    2: _provider(2, caps=("chat", "embedding", "vision", "ocr", "stt", "image_gen",
                          "image_edit")),
    3: _provider(3, caps=("chat",), enabled=False),
    4: _provider(4, protocol="deepl", caps=("translation",)),
    5: _provider(5, caps=("tts",)),
    6: _provider(6, protocol="docling", caps=("ocr",)),
    7: _provider(7, caps=("translation",)),
    10: _provider(10, caps=("tts",), voices=_STIMMEN),
}


@pytest.fixture
def route_env(monkeypatch):
    """Providers from _PROVIDERS, the stored route is recorded instead of written."""
    monkeypatch.setattr(admin.db, "get_provider", lambda pid: _PROVIDERS.get(pid))
    stored = MagicMock(side_effect=lambda feature, **kw: {"feature": feature, **kw})
    monkeypatch.setattr(admin.db, "set_route", stored)
    monkeypatch.setattr(feature_routes, "_measure_route_model", lambda *a, **kw: None)
    monkeypatch.setattr("src.routes.admin._embedding.invalidate_fingerprint_cache",
                        MagicMock())
    return stored


def _route(feature, locale="de", **body):
    body.setdefault("provider_id", 1)
    body.setdefault("model_name", "primary-model")
    return admin.set_feature_route(feature, SetFeatureRouteRequest(**body),
                                   _admin=None, locale=locale)


def _rejected(feature, **body):
    with pytest.raises(HTTPException) as exc:
        _route(feature, **body)
    assert exc.value.status_code == 422
    assert "admin.providers" not in exc.value.detail
    return exc.value.detail


def test_a_valid_fallback_is_stored(route_env):
    _route("chat", fallback_provider_id=2, provider_models={"2": "gemma-4-31b-it"})
    assert route_env.call_args.kwargs["fallback_provider_id"] == 2


def test_a_missing_fallback_is_stored_as_null(route_env):
    _route("chat")
    assert route_env.call_args.kwargs["fallback_provider_id"] is None


def test_without_a_first_choice_the_fallback_is_dropped(route_env):
    _route("chat", provider_id=None, fallback_provider_id=2, provider_models={"2": "m"})
    assert route_env.call_args.kwargs["fallback_provider_id"] is None


def test_tts_takes_a_fallback_with_voices(route_env):
    _route("tts", fallback_provider_id=10, provider_models={"1": "xtts-v2", "10": "qwen3-tts"})
    assert route_env.call_args.kwargs["fallback_provider_id"] == 10


def test_tts_may_fall_back_to_the_provider_of_its_route(route_env):
    """People choose their voice themselves, the route's own provider is a fine fallback for jobs on another one."""
    _route("tts", provider_id=10, fallback_provider_id=10, provider_models={"10": "xtts-v2"})
    assert route_env.call_args.kwargs["fallback_provider_id"] == 10


def test_tts_keeps_its_fallback_without_a_first_choice(route_env):
    """The voice page hides the first choice, so a missing one must not drop the fallback."""
    _route("tts", provider_id=None, fallback_provider_id=10, provider_models={"10": "xtts-v2"})
    assert route_env.call_args.kwargs["fallback_provider_id"] == 10


def test_a_tts_fallback_without_voices_is_rejected(route_env):
    """Without a voice the fallback could not take over a single job."""
    detail = _rejected("tts", fallback_provider_id=5, provider_models={"5": "qwen3-tts"})
    assert detail == admin.t("admin.providers.fallbackNoVoices", "de")
    route_env.assert_not_called()


def test_a_tts_fallback_whose_voices_have_no_id_is_rejected(route_env, monkeypatch):
    leer = _provider(11, caps=("tts",), voices=({"voice_id": "", "name": "?"},))
    monkeypatch.setattr(admin.db, "get_provider", lambda pid: leer if pid == 11 else _PROVIDERS.get(pid))
    _rejected("tts", fallback_provider_id=11, provider_models={"11": "qwen3-tts"})


def test_a_tts_fallback_still_needs_a_model(route_env):
    _rejected("tts", fallback_provider_id=10, provider_models={"1": "xtts-v2"})


def test_the_voice_message_exists_in_english_too(route_env):
    with pytest.raises(HTTPException) as de:
        _route("tts", fallback_provider_id=5, provider_models={"5": "m"})
    with pytest.raises(HTTPException) as en:
        _route("tts", locale="en", fallback_provider_id=5, provider_models={"5": "m"})
    assert de.value.detail != en.value.detail
    assert "admin.providers" not in en.value.detail


def test_the_fallback_must_differ_from_the_first_choice(route_env):
    _rejected("chat", fallback_provider_id=1, provider_models={"1": "m"})


def test_the_fallback_provider_must_exist(route_env):
    detail = _rejected("chat", fallback_provider_id=99, provider_models={"99": "m"})
    assert "99" in detail


def test_the_fallback_provider_must_be_enabled(route_env):
    _rejected("chat", fallback_provider_id=3, provider_models={"3": "m"})


@pytest.mark.parametrize("pid", [4, 6])
def test_the_fallback_provider_must_speak_openai_compat(route_env, pid):
    _rejected("ocr" if pid == 6 else "doc_translate", fallback_provider_id=pid,
              provider_models={str(pid): "m"})


@pytest.mark.parametrize("feature,capability", [
    ("chat", "chat"),
    ("doc_translate", "chat"),
    ("transcript_translate", "chat"),
    ("embedding", "embedding"),
    ("vision", "vision"),
    ("ocr", "ocr"),
    ("stt", "stt"),
    ("image_gen", "image_gen"),
    ("image_edit", "image_edit"),
    ("tts", "tts"),
])
def test_the_fallback_needs_the_capability_of_the_feature(route_env, monkeypatch,
                                                          feature, capability):
    fehlt = _provider(8, caps=[c for c in _PROVIDERS[2]["capabilities"] if c != capability]
                      + ["translation"], voices=_STIMMEN)
    hat = _provider(9, caps=(capability,), voices=_STIMMEN)
    monkeypatch.setattr(admin.db, "get_provider",
                        lambda pid: {8: fehlt, 9: hat}.get(pid) or _PROVIDERS.get(pid))
    modelle = {"1": "primary-model", "8": "primary-model", "9": "primary-model"}
    _rejected(feature, fallback_provider_id=8, provider_models=modelle)
    _route(feature, fallback_provider_id=9, provider_models=modelle)
    assert route_env.call_args.kwargs["fallback_provider_id"] == 9


def test_translation_alone_is_no_fallback_for_doc_translate(route_env):
    _rejected("doc_translate", fallback_provider_id=7, provider_models={"7": "m"})


@pytest.mark.parametrize("modelle", [{}, {"2": ""}, {"2": "   "}])
def test_the_fallback_needs_a_model(route_env, modelle):
    _rejected("chat", fallback_provider_id=2, provider_models=modelle)


def test_embedding_fallback_with_the_same_model_is_stored(route_env):
    _route("embedding", fallback_provider_id=2,
           provider_models={"1": "qwen3-embedding", "2": "qwen3-embedding"})
    assert route_env.call_args.kwargs["fallback_provider_id"] == 2


def test_embedding_fallback_compares_against_the_model_name_of_the_route(route_env):
    _route("embedding", model_name="qwen3-embedding", fallback_provider_id=2,
           provider_models={"2": "qwen3-embedding"})
    assert route_env.call_args.kwargs["fallback_provider_id"] == 2


def test_embedding_fallback_with_another_model_is_rejected(route_env):
    detail = _rejected("embedding", fallback_provider_id=2,
                       provider_models={"1": "qwen3-embedding", "2": "e5-large"})
    assert "qwen3-embedding" in detail


def test_the_fallback_messages_exist_in_english_too(route_env):
    with pytest.raises(HTTPException) as de:
        _route("chat", fallback_provider_id=1, provider_models={"1": "m"})
    with pytest.raises(HTTPException) as en:
        _route("chat", locale="en", fallback_provider_id=1, provider_models={"1": "m"})
    assert de.value.detail != en.value.detail
    assert "admin.providers" not in en.value.detail


def _route_test_env(monkeypatch, row):
    """The route test with a recorded probe, a job-level voice pick would fail loudly."""
    monkeypatch.setattr(admin.db, "list_routes", lambda: [row])
    monkeypatch.setattr(admin.db, "get_provider", lambda pid: _PROVIDERS.get(pid))
    monkeypatch.setattr("src.services.tts_job_provider.pick",
                        MagicMock(side_effect=AssertionError("route test must not pick")))
    probe = MagicMock(return_value=SimpleNamespace(status="error", error="x", warning=None))
    monkeypatch.setattr(feature_routes, "run_feature_route_test", probe)
    return probe


@pytest.mark.parametrize("provider_id,base_url", [(None, "http://p1"), (10, "http://p10")])
def test_the_tts_route_test_hits_exactly_the_named_provider(monkeypatch, provider_id, base_url):
    probe = _route_test_env(monkeypatch, _route_row("tts", 1, fallback=10,
                                                    models={"1": "xtts-v2", "10": "qwen3-tts"}))
    admin.test_route("tts", provider_id=provider_id, _admin=None, locale="de")
    assert probe.call_args.kwargs["base_url"] == base_url


# ─── Export and import ───────────────────────────────────────────────────────


def _route_row(feature, provider_id, *, fallback=None, models=None):
    return {
        "feature": feature, "provider_id": provider_id, "model_name": "primary-model",
        "user_choices": [], "provider_models": models or {}, "provider_sampling": {},
        "fallback_provider_id": fallback,
    }


def test_export_carries_the_caps_and_the_fallback_by_name(monkeypatch):
    monkeypatch.delenv("ASKF_SECRETS_KEY", raising=False)
    monkeypatch.setattr(admin.db, "list_providers", lambda: [
        _provider(1, "myLab", concurrency={"llm": 10}), _provider(2, "Lokal"),
    ])
    monkeypatch.setattr(admin.db, "list_routes", lambda: [
        _route_row("chat", 2, fallback=1, models={"1": "gemma-3", "2": "gemma-4-31b-it"}),
        _route_row("vision", 2, fallback=99),
        _route_row("ocr", 2),
    ])
    export = admin.build_export(exported_from=None)
    by_name = {p["name"]: p for p in export["providers"]}
    assert by_name["myLab"]["concurrency"] == {"llm": 10}
    assert by_name["Lokal"]["concurrency"] == {}
    by_feature = {r["feature"]: r for r in export["feature_routes"]}
    assert by_feature["chat"]["fallback_provider_name"] == "myLab"
    assert by_feature["vision"]["fallback_provider_name"] is None
    assert by_feature["ocr"]["fallback_provider_name"] is None


class _FakeDb:
    """Just enough of the database for an import, new rows get fresh ids."""

    def __init__(self, providers=None):
        self.providers = {p["id"]: dict(p) for p in providers or []}
        self.routes: dict[str, dict] = {}
        self._next = 100

    def list_providers(self):
        return list(self.providers.values())

    def list_routes(self):
        return list(self.routes.values())

    def create_provider(self, **kw):
        self._next += 1
        row = {"id": self._next, "api_key": kw.get("api_key"), **kw}
        row.setdefault("concurrency", {})
        self.providers[self._next] = row
        return row

    def update_provider(self, pid, **kw):
        self.providers[pid].update(kw)
        return self.providers[pid]

    def set_route(self, feature, **kw):
        self.routes[feature] = {"feature": feature, **kw}
        return self.routes[feature]


def _install(monkeypatch, fake):
    for name in ("list_providers", "list_routes", "create_provider", "update_provider",
                 "set_route"):
        monkeypatch.setattr(admin.db, name, getattr(fake, name))
    monkeypatch.setattr(provider_transfer, "probe_provider", lambda *a, **kw: None)
    monkeypatch.setattr("src.routes.admin._embedding.invalidate_fingerprint_cache",
                        MagicMock())


def test_export_then_import_keeps_caps_and_fallback(monkeypatch):
    monkeypatch.delenv("ASKF_SECRETS_KEY", raising=False)
    quelle = _FakeDb([_provider(1, "myLab", concurrency={"llm": 10, "tts": 4}),
                      _provider(2, "Lokal")])
    quelle.routes["chat"] = _route_row("chat", 2, fallback=1,
                                       models={"1": "gemma-3", "2": "gemma-4-31b-it"})
    _install(monkeypatch, quelle)
    export = admin.build_export(exported_from=None)

    ziel = _FakeDb()
    _install(monkeypatch, ziel)
    payload = ExportedConfig(**export).model_dump()
    admin.perform_import(payload)

    ids = {p["name"]: p["id"] for p in ziel.list_providers()}
    by_name = {p["name"]: p for p in ziel.list_providers()}
    assert by_name["myLab"]["concurrency"] == {"llm": 10, "tts": 4}
    assert by_name["Lokal"]["concurrency"] == {}
    chat = ziel.routes["chat"]
    assert chat["provider_id"] == ids["Lokal"]
    assert chat["fallback_provider_id"] == ids["myLab"]
    assert chat["provider_models"] == {str(ids["myLab"]): "gemma-3",
                                       str(ids["Lokal"]): "gemma-4-31b-it"}


def test_import_updates_the_caps_of_an_existing_provider(monkeypatch):
    ziel = _FakeDb([_provider(1, "myLab", concurrency={"tts": 4})])
    _install(monkeypatch, ziel)
    payload = ExportedConfig(**{
        "schema_version": 1, "exported_at": "x",
        "providers": [{"name": "myLab", "protocol": "openai_compat",
                       "base_url": "http://p1", "concurrency": {"llm": 10}}],
    }).model_dump()
    admin.perform_import(payload)
    assert ziel.providers[1]["concurrency"] == {"llm": 10}


def test_an_old_export_without_caps_keeps_the_existing_ones(monkeypatch):
    ziel = _FakeDb([_provider(1, "myLab", concurrency={"tts": 4})])
    _install(monkeypatch, ziel)
    payload = ExportedConfig(**{
        "schema_version": 1, "exported_at": "x",
        "providers": [{"name": "myLab", "protocol": "openai_compat",
                       "base_url": "http://p1"}],
    }).model_dump()
    admin.perform_import(payload)
    assert ziel.providers[1]["concurrency"] == {"tts": 4}


def test_export_then_import_keeps_the_tts_fallback(monkeypatch):
    monkeypatch.delenv("ASKF_SECRETS_KEY", raising=False)
    quelle = _FakeDb([_provider(1, "myLab", caps=("tts",), voices=_STIMMEN),
                      _provider(2, "Lokal", caps=("tts",), voices=_STIMMEN)])
    quelle.routes["tts"] = _route_row("tts", 2, fallback=1,
                                      models={"1": "xtts-v2", "2": "qwen3-tts"})
    _install(monkeypatch, quelle)
    export = admin.build_export(exported_from=None)

    ziel = _FakeDb()
    _install(monkeypatch, ziel)
    admin.perform_import(ExportedConfig(**export).model_dump())

    ids = {p["name"]: p["id"] for p in ziel.list_providers()}
    tts = ziel.routes["tts"]
    assert tts["provider_id"] == ids["Lokal"]
    assert tts["fallback_provider_id"] == ids["myLab"]
    stimmen = {p["name"]: p["voices"] for p in ziel.list_providers()}["myLab"]
    assert [v["voice_id"] for v in stimmen] == ["anna"]


def _roundtrip(monkeypatch, feature, provider_id, fallback, models):
    """Exports one route from a source and imports it into an empty target."""
    monkeypatch.delenv("ASKF_SECRETS_KEY", raising=False)
    quelle = _FakeDb([_provider(1, "myLab", caps=("tts", "chat"), voices=_STIMMEN),
                      _provider(2, "Lokal", caps=("tts", "chat"), voices=_STIMMEN)])
    quelle.routes[feature] = _route_row(feature, provider_id, fallback=fallback, models=models)
    _install(monkeypatch, quelle)
    export = admin.build_export(exported_from=None)
    ziel = _FakeDb()
    _install(monkeypatch, ziel)
    result = admin.perform_import(ExportedConfig(**export).model_dump())
    return ziel, {p["name"]: p["id"] for p in ziel.list_providers()}, result


def test_export_then_import_keeps_a_tts_fallback_on_the_route_provider(monkeypatch):
    """The admin allows a voice fallback on the route's own provider, the import must keep it."""
    ziel, ids, _ = _roundtrip(monkeypatch, "tts", 1, 1, {"1": "xtts-v2"})
    assert ziel.routes["tts"]["provider_id"] == ids["myLab"]
    assert ziel.routes["tts"]["fallback_provider_id"] == ids["myLab"]


def test_export_then_import_keeps_a_tts_route_with_only_a_fallback(monkeypatch):
    ziel, ids, result = _roundtrip(monkeypatch, "tts", None, 1, {"1": "xtts-v2"})
    tts = ziel.routes["tts"]
    assert tts["provider_id"] is None
    assert tts["fallback_provider_id"] == ids["myLab"]
    assert tts["provider_models"] == {str(ids["myLab"]): "xtts-v2"}
    assert result["routes_skipped"] == 0


def test_import_still_drops_a_chat_fallback_on_the_route_provider(monkeypatch):
    ziel, ids, _ = _roundtrip(monkeypatch, "chat", 1, 1, {"1": "gemma-3"})
    assert ziel.routes["chat"]["provider_id"] == ids["myLab"]
    assert ziel.routes["chat"]["fallback_provider_id"] is None


def test_import_still_skips_a_chat_route_with_only_a_fallback(monkeypatch):
    ziel, _, result = _roundtrip(monkeypatch, "chat", None, 1, {"1": "gemma-3"})
    assert "chat" not in ziel.routes
    assert result["routes_skipped"] == 1


def test_import_skips_a_tts_route_whose_only_fallback_is_unknown(monkeypatch):
    ziel = _FakeDb()
    _install(monkeypatch, ziel)
    payload = ExportedConfig(**{
        "schema_version": 1, "exported_at": "x",
        "feature_routes": [{"feature": "tts", "fallback_provider_name": "Ghost"}],
    }).model_dump()
    assert admin.perform_import(payload)["routes_skipped"] == 1
    assert "tts" not in ziel.routes


@pytest.mark.parametrize("feature,action", [("tts", "create"), ("chat", "skip_unresolved")])
def test_preview_shows_a_route_with_only_a_fallback_like_the_import(monkeypatch, feature, action):
    monkeypatch.setattr(admin.db, "list_providers", lambda: [_provider(1, "myLab")])
    monkeypatch.setattr(admin.db, "get_route", lambda feature: None)
    preview = admin.build_import_preview({
        "schema_version": 1, "providers": [],
        "feature_routes": [{"feature": feature, "provider_name": None,
                            "fallback_provider_name": "myLab"}],
    })
    assert preview["routes"][0]["action"] == action


def test_import_drops_an_unresolved_fallback(monkeypatch):
    ziel = _FakeDb([_provider(1, "Lokal")])
    _install(monkeypatch, ziel)
    payload = ExportedConfig(**{
        "schema_version": 1, "exported_at": "x",
        "feature_routes": [{"feature": "chat", "provider_name": "Lokal",
                            "fallback_provider_name": "Ghost"}],
    }).model_dump()
    admin.perform_import(payload)
    assert ziel.routes["chat"]["fallback_provider_id"] is None


@pytest.mark.parametrize("caps", [{"gpu": 2}, {"llm": 0}, {"llm": 1001}])
def test_import_rejects_invalid_caps(caps):
    cfg = {
        "schema_version": 1, "exported_at": "x", "feature_routes": [],
        "providers": [{"name": "A", "protocol": "openai_compat", "base_url": "http://a",
                       "capabilities": [], "concurrency": caps}],
    }
    with pytest.raises(HTTPException) as exc:
        admin.validate_import_config(cfg)
    assert exc.value.status_code == 400


# ─── Repository wiring without a database ────────────────────────────────────


class _Cursor:
    def __init__(self, calls, row):
        self._calls, self._row = calls, row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, calls, row):
        self._calls, self._row = calls, row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self, **kwargs):
        return _Cursor(self._calls, self._row)

    def commit(self):
        pass


def test_create_provider_appends_the_caps_after_the_old_params(monkeypatch):
    from src.features.ai_providers.repository import providers as repo

    calls: list[tuple] = []
    row = {**_provider(1), "concurrency": '{"llm": 10}', "capabilities": "[]", "voices": "[]"}
    monkeypatch.setattr(repo, "get_connection", lambda: _Conn(calls, row))
    result = repo.create_provider(name="A", protocol="openai_compat", base_url="http://x",
                                  api_key=None, concurrency={"llm": 10})
    sql, params = [c for c in calls if "INSERT INTO providers" in c[0]][0]
    assert "concurrency" in sql
    # The owner column came later still, an admin's provider belongs to nobody.
    assert params[-2:] == ('{"llm": 10}', None)
    assert result["concurrency"] == {"llm": 10}


def test_a_row_without_the_column_reads_as_no_caps():
    from src.features.ai_providers.repository import providers as repo

    row = {"id": 1, "api_key": None, "capabilities": "[]", "voices": "[]"}
    assert repo._row_to_dict(row)["concurrency"] == {}


def test_set_route_writes_the_fallback(monkeypatch):
    from src.features.ai_providers.repository import feature_routes as repo

    calls: list[tuple] = []
    row = {"feature": "chat", "provider_id": 1, "fallback_provider_id": 2,
           "user_choices": "[]", "provider_models": "{}", "provider_sampling": "{}"}
    monkeypatch.setattr(repo, "get_connection", lambda: _Conn(calls, row))
    result = repo.set_route("chat", provider_id=1, fallback_provider_id=2)
    sql, params = [c for c in calls if "INSERT INTO feature_routes" in c[0]][0]
    assert "fallback_provider_id = EXCLUDED.fallback_provider_id" in sql
    assert 2 in params
    assert result["fallback_provider_id"] == 2


# ─── Real database ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def verbindung():
    """A database connection or a clean skip."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("kein DATABASE_URL gesetzt (Test braucht echtes Postgres)")
    from src.core.db.pool import get_connection
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception as fehler:  # pragma: no cover - only outside the stack
        pytest.skip(f"Datenbank nicht erreichbar: {fehler}")
    return get_connection


def test_the_caps_are_seeded_only_when_the_column_is_new(verbindung):
    """Runs in a throwaway schema, so the real providers table stays untouched."""
    from src import limits
    from src.core.db import schema as schema_mod

    name = f"test_rueckfall_{uuid.uuid4().hex[:8]}"
    with verbindung() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(f"CREATE SCHEMA {name}")
                cur.execute(f"SET LOCAL search_path TO {name}")
                cur.execute("CREATE TABLE providers (id SERIAL PRIMARY KEY, name TEXT, "
                            "capabilities JSONB NOT NULL DEFAULT '[]'::jsonb)")
                cur.execute(
                    "INSERT INTO providers (name, capabilities) VALUES "
                    "('stimme', '[\"tts\"]'), ('bild', '[\"image_gen\"]'), "
                    "('bearbeiten', '[\"image_edit\", \"tts\"]'), ('text', '[\"chat\"]')"
                )
                assert schema_mod._add_provider_concurrency_once(cur) is True
                cur.execute("SELECT name, concurrency FROM providers")
                assert dict(cur.fetchall()) == {
                    "stimme": {"tts": limits.TTS_PROVIDER_MAX_CONCURRENT},
                    "bild": {"image": limits.IMAGE_PROVIDER_MAX_CONCURRENT},
                    "bearbeiten": {"tts": limits.TTS_PROVIDER_MAX_CONCURRENT,
                                   "image": limits.IMAGE_PROVIDER_MAX_CONCURRENT},
                    "text": {},
                }
                # The admin clears a cap, the next start must not bring it back.
                cur.execute("UPDATE providers SET concurrency = '{}'::jsonb "
                            "WHERE name = 'stimme'")
                assert schema_mod._add_provider_concurrency_once(cur) is False
                cur.execute("SELECT concurrency FROM providers WHERE name = 'stimme'")
                assert cur.fetchone()[0] == {}
        finally:
            conn.rollback()


def test_repository_round_trip_on_the_real_schema(verbindung):
    from src.core.db.schema import init_db
    from src.features.ai_providers.repository import feature_routes as routes_repo
    from src.features.ai_providers.repository import providers as repo

    init_db()
    kennung = uuid.uuid4().hex[:8]
    feature = f"test_rueckfall_{kennung}"
    a = repo.create_provider(name=f"test-rueckfall-a-{kennung}", protocol="openai_compat",
                             base_url="http://a", capabilities=["chat"],
                             concurrency={"llm": 10})
    b = repo.create_provider(name=f"test-rueckfall-b-{kennung}", protocol="openai_compat",
                             base_url="http://b", capabilities=["chat"])
    try:
        assert a["concurrency"] == {"llm": 10}
        assert b["concurrency"] == {}
        assert repo.get_provider(a["id"])["concurrency"] == {"llm": 10}
        assert any(p["id"] == a["id"] and p["concurrency"] == {"llm": 10}
                   for p in repo.list_providers())
        assert repo.update_provider(a["id"], concurrency={"llm": 3, "tts": 2})[
            "concurrency"] == {"llm": 3, "tts": 2}
        assert repo.update_provider(a["id"], concurrency={})["concurrency"] == {}

        route = routes_repo.set_route(feature, provider_id=a["id"], model_name="m",
                                      provider_models={str(b["id"]): "m-b"},
                                      fallback_provider_id=b["id"])
        assert route["fallback_provider_id"] == b["id"]
        assert routes_repo.get_route(feature)["fallback_provider_id"] == b["id"]
        assert any(r["feature"] == feature for r in routes_repo.routes_using_provider(b["id"]))

        routes_repo.clear_provider_from_routes(b["id"])
        assert routes_repo.get_route(feature)["fallback_provider_id"] is None

        routes_repo.set_route(feature, provider_id=a["id"], fallback_provider_id=b["id"])
        assert routes_repo.set_route(feature, provider_id=a["id"])["fallback_provider_id"] is None

        # Deleting the provider behind a fallback empties the column by itself.
        routes_repo.set_route(feature, provider_id=a["id"], fallback_provider_id=b["id"])
        repo.delete_provider(b["id"])
        assert routes_repo.get_route(feature)["fallback_provider_id"] is None
    finally:
        with verbindung() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM feature_routes WHERE feature = %s", (feature,))
                cur.execute("DELETE FROM providers WHERE id IN (%s, %s)", (a["id"], b["id"]))
            conn.commit()
