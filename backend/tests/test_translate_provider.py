from unittest.mock import MagicMock


def _make_provider(id, name, protocol="openai_compat", api_key=None, base_url="http://example.com"):
    return {"id": id, "name": name, "protocol": protocol, "api_key": api_key,
            "base_url": base_url, "enabled": True, "voices": [], "capabilities": []}


def test_get_translation_providers_merges_translation_and_chat(monkeypatch):
    from src.dependencies import get_translation_providers
    p1 = _make_provider(1, "DeepL", protocol="deepl")
    p2 = _make_provider(2, "Anbieter A", protocol="openai_compat")
    p3 = _make_provider(2, "Anbieter A", protocol="openai_compat")  # duplicate, different cap

    def fake_list(cap):
        if cap == "translation":
            return [p1]
        if cap == "chat":
            return [p2, p3]
        return []

    monkeypatch.setattr("src.dependencies.db.list_providers_with_capability", fake_list)
    monkeypatch.setattr("src.dependencies.db.get_route", lambda f: None)
    result = get_translation_providers()
    ids = [p["id"] for p in result]
    assert ids == [1, 2], "should deduplicate and preserve order"


def test_die_erste_wahl_aus_dem_admin_steht_vorn(monkeypatch):
    """Run 18: translator and screencast took the oldest provider instead of the admin's first choice."""
    from src.dependencies import get_translation_providers
    gwdg, mylab, lokal = _make_provider(20, "GWDG"), _make_provider(21, "myLab"), _make_provider(92, "Lokal")
    monkeypatch.setattr("src.dependencies.db.list_providers_with_capability",
                        lambda cap: [gwdg, mylab, lokal] if cap == "chat" else [])
    monkeypatch.setattr("src.dependencies.db.get_route",
                        lambda f: {"provider_id": 92} if f == "doc_translate" else None)
    assert [p["id"] for p in get_translation_providers()] == [92, 20, 21]


def test_eine_erste_wahl_ohne_uebersetzung_aendert_die_reihenfolge_nicht(monkeypatch):
    from src.dependencies import get_translation_providers
    gwdg, mylab = _make_provider(20, "GWDG"), _make_provider(21, "myLab")
    monkeypatch.setattr("src.dependencies.db.list_providers_with_capability",
                        lambda cap: [gwdg, mylab] if cap == "chat" else [])
    monkeypatch.setattr("src.dependencies.db.get_route", lambda f: {"provider_id": 99})
    assert [p["id"] for p in get_translation_providers()] == [20, 21]


def test_get_translate_client_for_provider_deepl(monkeypatch):
    from src.dependencies import get_translate_client_for_provider
    from src.services.glossary import GlossaryService

    provider = _make_provider(5, "DeepL", protocol="deepl", api_key="secret:fx",
                              base_url="https://api-free.deepl.com")
    route = {"provider_models": {"5": ""}, "model_name": None}

    monkeypatch.setattr("src.dependencies.db.get_provider", lambda pid: provider)
    monkeypatch.setattr("src.dependencies.db.get_route", lambda f: route)

    client, glossary = get_translate_client_for_provider(5, glossary_entries={"Hello": "Hallo"})
    from src.services.deepl_client import DeepLClient
    assert isinstance(client, DeepLClient)
    assert isinstance(glossary, GlossaryService)


def test_get_translate_client_for_provider_llm(monkeypatch):
    from src.dependencies import get_translate_client_for_provider

    provider = _make_provider(7, "Anbieter A", protocol="openai_compat", api_key="key",
                              base_url="https://llm.example.com/v1")
    route = {"provider_models": {"7": "mistral-small"}, "model_name": None}

    monkeypatch.setattr("src.dependencies.db.get_provider", lambda pid: provider)
    monkeypatch.setattr("src.dependencies.db.get_route", lambda f: route)

    client, glossary = get_translate_client_for_provider(7, glossary_entries=None)
    from src.services.llm_translation_client import LLMTranslationClient
    assert isinstance(client, LLMTranslationClient)


def test_get_translate_client_returns_none_for_missing_provider(monkeypatch):
    from src.dependencies import get_translate_client_for_provider

    monkeypatch.setattr("src.dependencies.db.get_provider", lambda pid: None)

    client, glossary = get_translate_client_for_provider(99)
    assert client is None


def test_get_translate_client_fallback_when_provider_id_none(monkeypatch):
    from src.dependencies import get_translation_providers, get_translate_client_for_provider

    provider = _make_provider(3, "DeepL", protocol="deepl", api_key="key")
    route = {"provider_models": {}, "model_name": None}

    monkeypatch.setattr("src.dependencies.db.list_providers_with_capability",
                        lambda cap: [provider] if cap == "translation" else [])
    monkeypatch.setattr("src.dependencies.db.get_provider", lambda pid: provider)
    monkeypatch.setattr("src.dependencies.db.get_route", lambda f: route)

    client, glossary = get_translate_client_for_provider(None)
    from src.services.deepl_client import DeepLClient
    assert isinstance(client, DeepLClient)


def test_get_translate_client_returns_none_for_disabled_provider(monkeypatch):
    from src.dependencies import get_translate_client_for_provider
    provider = _make_provider(10, "DeepL", protocol="deepl", api_key="key")
    provider["enabled"] = False
    monkeypatch.setattr("src.dependencies.db.get_provider", lambda pid: provider)
    client, glossary = get_translate_client_for_provider(10)
    assert client is None


def test_get_translate_client_returns_none_when_no_providers_available(monkeypatch):
    from src.dependencies import get_translate_client_for_provider
    monkeypatch.setattr("src.dependencies.db.list_providers_with_capability", lambda cap: [])
    # Without a route there is no first choice either, so nothing is left to translate with.
    monkeypatch.setattr("src.dependencies.db.get_route", lambda f: None)
    client, glossary = get_translate_client_for_provider(None)
    assert client is None


def test_run_translate_uses_provider_id(monkeypatch, tmp_path):
    """run_translate resolves provider_id into the right translation client."""
    from src.tasks import general_tasks

    provider = _make_provider(5, "DeepL", protocol="deepl", api_key="key",
                              base_url="https://api-free.deepl.com")
    glossary_svc = MagicMock()
    fake_client = MagicMock()
    fake_client.translate_text.return_value = "translated"
    fake_client.translate_batch.return_value = ["translated"]

    monkeypatch.setattr("src.dependencies.db.get_provider", lambda pid: provider)
    monkeypatch.setattr("src.dependencies.db.get_route", lambda f: {"provider_models": {}, "model_name": None})
    monkeypatch.setattr("src.dependencies.db.list_providers_with_capability", lambda c: [provider])

    captured = {}

    def fake_get_translate_client(pid, *, glossary_entries=None):
        captured["provider_id"] = pid
        return fake_client, glossary_svc

    monkeypatch.setattr("src.tasks.general_tasks.get_translate_client_for_provider",
                        fake_get_translate_client)

    # Minimal stubs so the task body can run without DB/Celery
    monkeypatch.setattr("src.tasks.general_tasks.db.update_job_status", lambda *a, **kw: None)
    monkeypatch.setattr("src.tasks.general_tasks.db.update_job_expiry", lambda *a, **kw: None)
    monkeypatch.setattr("src.tasks.general_tasks._resolve_user_id", lambda uuid: 1)

    txt = tmp_path / "input.txt"
    txt.write_text("Hello world")

    monkeypatch.setattr("src.tasks.general_tasks.TranslationService",
                        lambda deepl_client, glossary: MagicMock(
                            translate_text=lambda t, s, tgt: "translated",
                            translate_filename=lambda f, s, tgt: "translated.txt",
                        ))

    result_path = tmp_path / "result.txt"
    monkeypatch.setattr("src.tasks.general_tasks.get_file", lambda p: b"Hello world")
    monkeypatch.setattr("src.tasks.general_tasks.save_result_file", lambda *a, **kw: str(result_path))
    monkeypatch.setattr("src.tasks.general_tasks.save_result_and_evict", lambda *a, **kw: None)
    monkeypatch.setattr("src.tasks.general_tasks.delete_file", lambda p: None)

    general_tasks.run_translate(
        "job-uuid-123",
        str(txt),
        "test.txt",
        "",   # glossary_json
        "DE",
        "EN",
        5,    # provider_id
    )

    assert captured["provider_id"] == 5
