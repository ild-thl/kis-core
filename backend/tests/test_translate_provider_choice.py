"""The translation picker only offers providers that answer right now."""


async def test_translate_config_hides_unreachable(monkeypatch):
    from src.routes import translate
    from src.services import feature_provider_choices

    anbieter = [{"id": 92, "name": "Lokal"}, {"id": 21, "name": "THL myLab"}]
    monkeypatch.setattr("src.dependencies.get_translation_providers", lambda: anbieter)

    async def fake_reachable(provider):
        return provider["id"] != 92

    monkeypatch.setattr(feature_provider_choices, "_is_reachable", fake_reachable)
    from src.services import provider_check

    monkeypatch.setattr(provider_check, "refused_ids", lambda feature, ids=None: set())

    result = await translate.get_translate_config(current_user={}, locale="de")
    assert result["providers"] == [{"id": 21, "label": "THL myLab"}]


async def test_das_dropdown_bekommt_nur_erreichbare_anbieter(monkeypatch):
    from src.routes import translate
    from src.services import feature_provider_choices, provider_check

    anbieter = [{"id": 92, "name": "Lokal"}, {"id": 21, "name": "THL myLab"}]
    monkeypatch.setattr("src.dependencies.get_translation_providers", lambda: anbieter)

    async def fake_reachable(provider):
        return provider["id"] != 92

    monkeypatch.setattr(feature_provider_choices, "_is_reachable", fake_reachable)
    monkeypatch.setattr(provider_check, "refused_ids", lambda feature, ids=None: set())

    result = await translate.get_translate_providers(current_user={})
    assert result == {"providers": [{"id": 21, "name": "THL myLab"}], "default_id": 21}


def test_die_sprachen_warten_nicht_auf_die_anbieter(monkeypatch):
    from src.routes import translate

    def nie_fragen():
        raise AssertionError("languages must not touch the providers")

    monkeypatch.setattr("src.dependencies.get_translation_providers", nie_fragen)

    result = translate.get_translate_languages(current_user={}, locale="de")
    assert "providers" not in result
    assert result["languages"] and result["default_target"]
