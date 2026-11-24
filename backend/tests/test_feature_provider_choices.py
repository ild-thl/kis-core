"""Checks the provider choice by capability for speech recognition and image tools."""

import pytest

from src.services import feature_provider_choices as svc
from src.services.feature_router import FeatureNotConfigured


@pytest.fixture(autouse=True)
def _keine_gescheiterten_pruefungen(monkeypatch):
    from src.services import provider_check

    monkeypatch.setattr(provider_check, "refused_ids", lambda feature, ids=None: set())


def _route(provider_id=20, model_name="primary-model", provider_models=None):
    return {
        "provider_id": provider_id,
        "model_name": model_name,
        "provider_models": provider_models or {},
    }


def _provider(pid, *, caps=("stt",), enabled=True, base_url=None):
    return {
        "id": pid,
        "name": f"P{pid}",
        "protocol": "openai_compat",
        "base_url": base_url or f"http://p{pid}",
        "api_key": None,
        "enabled": enabled,
        "capabilities": list(caps),
    }


# ─── _model_for ──────────────────────────────────────────────────────────────


def test_model_for_explicit_per_provider_wins():
    route = _route(20, "primary-model", {"21": "explicit-21"})
    assert svc._model_for(route, 21) == "explicit-21"


def test_model_for_primary_inherits_model_name():
    assert svc._model_for(_route(20, "primary-model", {}), 20) == "primary-model"


def test_model_for_non_primary_without_explicit_is_empty():
    assert svc._model_for(_route(20, "primary-model", {}), 21) == ""


# ─── is_eligible ─────────────────────────────────────────────────────────────


def test_is_eligible(monkeypatch):
    providers = [_provider(20), _provider(21), _provider(22)]
    monkeypatch.setattr(svc.db, "list_providers_with_capability", lambda cap: providers)
    # 20 is primary (inherits model_name); 21 has explicit; 22 has neither.
    monkeypatch.setattr(svc.db, "get_route", lambda f: _route(20, "m", {"21": "m21"}))

    assert svc.is_eligible("stt", 20) is True
    assert svc.is_eligible("stt", 21) is True
    assert svc.is_eligible("stt", 22) is False  # capability but no model
    assert svc.is_eligible("stt", 99) is False  # not capability-eligible


# ─── resolve_binding ─────────────────────────────────────────────────────────


def test_resolve_binding_ok(monkeypatch):
    monkeypatch.setattr(svc.db, "get_provider", lambda pid: _provider(21, caps=("vision",)))
    monkeypatch.setattr(svc.db, "get_route", lambda f: _route(20, "primary", {"21": "vl-model"}))

    binding = svc.resolve_binding("vision", 21)
    assert binding.model == "vl-model"
    assert binding.provider["id"] == 21


def test_resolve_binding_disabled(monkeypatch):
    monkeypatch.setattr(svc.db, "get_provider", lambda pid: _provider(21, enabled=False))
    monkeypatch.setattr(svc.db, "get_route", lambda f: _route())
    with pytest.raises(FeatureNotConfigured, match="unavailable"):
        svc.resolve_binding("stt", 21)


def test_resolve_binding_missing_capability(monkeypatch):
    monkeypatch.setattr(svc.db, "get_provider", lambda pid: _provider(21, caps=("chat",)))
    monkeypatch.setattr(svc.db, "get_route", lambda f: _route(21, "m", {}))
    with pytest.raises(FeatureNotConfigured, match="capability"):
        svc.resolve_binding("stt", 21)


def test_resolve_binding_no_model(monkeypatch):
    monkeypatch.setattr(svc.db, "get_provider", lambda pid: _provider(21))
    # 21 is neither primary nor has an explicit model -> no model
    monkeypatch.setattr(svc.db, "get_route", lambda f: _route(20, "primary", {}))
    with pytest.raises(FeatureNotConfigured, match="no model"):
        svc.resolve_binding("stt", 21)


# ─── list_reachable_choices ──────────────────────────────────────────────────


class _FakeAdapter:
    def __init__(self, status):
        self._status = status

    def probe(self):
        from src.services.protocols.base import ProbeResult

        return ProbeResult(capabilities=[], status=self._status, error=None)


async def test_list_reachable_filters_unreachable(monkeypatch):
    providers = [_provider(20, base_url="http://ok"), _provider(21, base_url="http://down")]
    monkeypatch.setattr(svc.db, "list_providers_with_capability", lambda cap: providers)
    monkeypatch.setattr(svc.db, "get_route", lambda f: _route(21, "m", {"20": "m20", "21": "m21"}))
    monkeypatch.setattr(
        svc,
        "make_adapter",
        lambda *, protocol, base_url, api_key: _FakeAdapter("ok" if base_url == "http://ok" else "error"),
    )

    result = await svc.list_reachable_choices("stt")
    assert [p["id"] for p in result["providers"]] == [20]
    # default (21) unreachable -> falls back to first reachable (20)
    assert result["default_id"] == 20


async def test_ist_die_erste_wahl_weg_steht_der_rueckfall_aus_dem_admin_vorn(monkeypatch):
    """The large image model was still waiting, yet the oldest provider was preselected instead of the small one."""
    providers = [_provider(20, base_url="http://gwdg"), _provider(21, base_url="http://mylab"),
                 _provider(93, base_url="http://down"), _provider(95, base_url="http://klein")]
    route = {**_route(93, "m", {"20": "m", "21": "m", "93": "m", "95": "m"}), "fallback_provider_id": 95}
    monkeypatch.setattr(svc.db, "list_providers_with_capability", lambda cap: providers)
    monkeypatch.setattr(svc.db, "get_route", lambda f: route)
    monkeypatch.setattr(svc, "make_adapter",
                        lambda *, protocol, base_url, api_key: _FakeAdapter("error" if base_url == "http://down" else "ok"))

    result = await svc.list_reachable_choices("image_gen")
    assert result["default_id"] == 95


async def test_list_reachable_keeps_default(monkeypatch):
    providers = [_provider(20, base_url="http://a"), _provider(21, base_url="http://b")]
    monkeypatch.setattr(svc.db, "list_providers_with_capability", lambda cap: providers)
    monkeypatch.setattr(svc.db, "get_route", lambda f: _route(21, "m", {"20": "m20", "21": "m21"}))
    monkeypatch.setattr(svc, "make_adapter", lambda **kw: _FakeAdapter("ok"))

    result = await svc.list_reachable_choices("stt")
    assert {p["id"] for p in result["providers"]} == {20, 21}
    assert result["default_id"] == 21


async def test_list_reachable_empty_when_no_models(monkeypatch):
    # capability-eligible but no models configured -> nothing to offer
    monkeypatch.setattr(svc.db, "list_providers_with_capability", lambda cap: [_provider(20), _provider(21)])
    monkeypatch.setattr(svc.db, "get_route", lambda f: _route(99, "", {}))

    result = await svc.list_reachable_choices("stt")
    assert result == {"providers": [], "default_id": None}


# ─── fallback_candidates ───────────────────────────────────────────────────


def _fallback_db(monkeypatch, providers, route):
    """Both lookups the fallback needs, route and provider, from the same fake."""
    monkeypatch.setattr(svc.db, "list_providers_with_capability", lambda cap: providers)
    monkeypatch.setattr(svc.db, "get_route", lambda f: route)
    monkeypatch.setattr(svc.db, "get_provider", lambda pid: next((p for p in providers if p["id"] == pid), None))


def test_fallback_candidates_is_only_the_admins_fallback(monkeypatch):
    providers = [_provider(20, caps=("chat",)), _provider(21, caps=("chat",)), _provider(22, caps=("chat",))]
    _fallback_db(monkeypatch, providers, {**_route(20, "m", {"21": "m", "22": "m"}), "fallback_provider_id": 22})

    chain = svc.fallback_candidates("chat")
    assert [b.provider["id"] for b in chain] == [22]


def test_fallback_candidates_without_a_set_fallback_is_empty(monkeypatch):
    """Other providers with a model no longer stand in by themselves, only the admin decides."""
    providers = [_provider(20, caps=("chat",)), _provider(21, caps=("chat",))]
    _fallback_db(monkeypatch, providers, _route(20, "m", {"21": "m"}))

    assert svc.fallback_candidates("chat") == []


def test_fallback_candidates_chat_allows_different_model(monkeypatch):
    providers = [_provider(20, caps=("chat",)), _provider(21, caps=("chat",))]
    # 21 has its own model, different from the primary's.
    _fallback_db(monkeypatch, providers,
                 {**_route(20, "primary-model", {"21": "other-model"}), "fallback_provider_id": 21})

    chain = svc.fallback_candidates("chat")
    assert [b.model for b in chain] == ["other-model"]


def test_fallback_candidates_embedding_skips_different_model(monkeypatch):
    providers = [_provider(20, caps=("embedding",)), _provider(21, caps=("embedding",))]
    # 21 is the set fallback with a model, but it differs from the primary's.
    _fallback_db(monkeypatch, providers,
                 {**_route(20, "bge-m3", {"21": "different-model"}), "fallback_provider_id": 21})

    assert svc.fallback_candidates("embedding") == []


def test_fallback_candidates_embedding_keeps_same_model(monkeypatch):
    providers = [_provider(20, caps=("embedding",)), _provider(21, caps=("embedding",))]
    # Both providers are explicitly configured with the identical model name.
    _fallback_db(monkeypatch, providers, {**_route(20, "bge-m3", {"21": "bge-m3"}), "fallback_provider_id": 21})

    chain = svc.fallback_candidates("embedding")
    assert [(b.provider["id"], b.model) for b in chain] == [(21, "bge-m3")]


def test_fallback_candidates_no_route_is_empty(monkeypatch):
    monkeypatch.setattr(svc.db, "list_providers_with_capability", lambda cap: [_provider(20)])
    monkeypatch.setattr(svc.db, "get_route", lambda f: None)

    assert svc.fallback_candidates("chat") == []


def test_fallback_candidates_no_other_providers_is_empty(monkeypatch):
    monkeypatch.setattr(svc.db, "list_providers_with_capability", lambda cap: [_provider(20, caps=("chat",))])
    monkeypatch.setattr(svc.db, "get_route", lambda f: _route(20, "m", {}))

    assert svc.fallback_candidates("chat") == []


# ─── binding_for ─────────────────────────────────────────────────────────────


def test_binding_for_without_choice_takes_the_admin_route(monkeypatch):
    monkeypatch.setattr(svc.feature_router, "resolve", lambda f: f"route:{f}")
    assert svc.binding_for("chat", None) == "route:chat"


def test_binding_for_takes_the_chosen_provider(monkeypatch):
    monkeypatch.setattr(svc.db, "get_provider", lambda pid: _provider(21, caps=("chat",)))
    monkeypatch.setattr(svc.db, "get_route", lambda f: _route(20, "primary", {"21": "m21"}))
    binding = svc.binding_for("chat", 21)
    assert binding.provider["id"] == 21
    assert binding.model == "m21"


def test_binding_for_falls_back_when_the_choice_is_gone(monkeypatch):
    monkeypatch.setattr(svc.db, "get_provider", lambda pid: _provider(21, caps=("chat",), enabled=False))
    monkeypatch.setattr(svc.db, "get_route", lambda f: _route(20, "primary", {"21": "m21"}))
    monkeypatch.setattr(svc.feature_router, "resolve", lambda f: "admin-route")
    assert svc.binding_for("chat", 21) == "admin-route"


async def test_list_reachable_names_the_model_of_each_provider(monkeypatch):
    providers = [_provider(20, caps=("chat",)), _provider(21, caps=("chat",))]
    monkeypatch.setattr(svc.db, "list_providers_with_capability", lambda cap: providers)
    monkeypatch.setattr(svc.db, "get_route", lambda f: _route(21, "m21", {"20": "m20"}))
    monkeypatch.setattr(svc, "make_adapter", lambda **kw: _FakeAdapter("ok"))
    result = await svc.list_reachable_choices("chat")
    assert {p["id"]: p["model"] for p in result["providers"]} == {20: "m20", 21: "m21"}


# ─── _is_reachable ───────────────────────────────────────────────────────────


class _CountingAdapter:
    def __init__(self, calls, status):
        self._calls = calls
        self._status = status

    def probe(self):
        from src.services.protocols.base import ProbeResult

        self._calls.append(1)
        return ProbeResult(capabilities=[], status=self._status, error=None)


async def test_ein_frischer_ping_wird_nicht_wiederholt(monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "make_adapter", lambda **kw: _CountingAdapter(calls, "ok"))
    provider = _provider(20)

    assert await svc._is_reachable(provider) is True
    assert await svc._is_reachable(provider) is True
    assert len(calls) == 1


async def test_ein_alter_ping_antwortet_sofort_und_wird_im_hintergrund_erneuert(monkeypatch):
    import asyncio
    import time

    calls = []
    monkeypatch.setattr(svc, "make_adapter", lambda **kw: _CountingAdapter(calls, "error"))
    provider = _provider(20)
    svc._probed[svc._probe_key(provider)] = (time.time() - svc.PROVIDER_PROBE_MAX_AGE_SECONDS - 1, True)

    # The old answer comes back without waiting, the renewal flips it for the next opening.
    assert await svc._is_reachable(provider) is True
    await asyncio.gather(*svc._probing.values())
    assert len(calls) == 1
    assert await svc._is_reachable(provider) is False


async def test_eine_neue_adresse_wird_neu_gepingt(monkeypatch):
    import time

    calls = []
    monkeypatch.setattr(svc, "make_adapter", lambda **kw: _CountingAdapter(calls, "error"))
    svc._probed[svc._probe_key(_provider(20, base_url="http://alt"))] = (time.time(), True)

    assert await svc._is_reachable(_provider(20, base_url="http://neu")) is False
    assert len(calls) == 1


async def test_gleichzeitige_erste_anfragen_pingen_nur_einmal(monkeypatch):
    import asyncio

    calls = []
    monkeypatch.setattr(svc, "make_adapter", lambda **kw: _CountingAdapter(calls, "ok"))
    provider = _provider(20)

    assert await asyncio.gather(*(svc._is_reachable(provider) for _ in range(5))) == [True] * 5
    assert len(calls) == 1


async def test_eine_neue_adresse_raeumt_das_alte_ergebnis_weg(monkeypatch):
    import time

    monkeypatch.setattr(svc, "make_adapter", lambda **kw: _CountingAdapter([], "ok"))
    alt = svc._probe_key(_provider(20, base_url="http://alt"))
    svc._probed[alt] = (time.time(), True)

    await svc._is_reachable(_provider(20, base_url="http://neu"))
    assert alt not in svc._probed
