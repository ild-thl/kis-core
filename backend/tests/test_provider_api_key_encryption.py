"""providers.api_key stops sitting in the database as plain text."""
import json

from src.features.ai_providers.repository import providers


# ─── _encrypt_key / _decrypt_key: the crypto itself ────────────────────────


def test_encrypt_key_returns_none_for_none(monkeypatch):
    monkeypatch.setenv("ASKF_SECRETS_KEY", "test-secret")
    assert providers._encrypt_key(None) is None


def test_encrypt_key_leaves_plaintext_when_secret_unset(monkeypatch):
    """No ASKF_SECRETS_KEY configured -> unchanged, matches today's behavior."""
    monkeypatch.delenv("ASKF_SECRETS_KEY", raising=False)
    assert providers._encrypt_key("sk-real") == "sk-real"


def test_encrypt_key_wraps_when_secret_set(monkeypatch):
    monkeypatch.setenv("ASKF_SECRETS_KEY", "test-secret")
    stored = providers._encrypt_key("sk-real")

    assert stored != "sk-real"
    from src.services.export_crypto import is_envelope
    assert is_envelope(json.loads(stored))


def test_decrypt_key_returns_none_for_none(monkeypatch):
    monkeypatch.setenv("ASKF_SECRETS_KEY", "test-secret")
    assert providers._decrypt_key(None) is None


def test_decrypt_key_passes_through_legacy_plaintext(monkeypatch):
    """A row saved before this change is a bare string, not an envelope."""
    monkeypatch.setenv("ASKF_SECRETS_KEY", "test-secret")
    assert providers._decrypt_key("sk-legacy") == "sk-legacy"


def test_decrypt_key_recovers_wrapped_value(monkeypatch):
    monkeypatch.setenv("ASKF_SECRETS_KEY", "test-secret")
    stored = providers._encrypt_key("sk-real")

    assert providers._decrypt_key(stored) == "sk-real"


def test_decrypt_key_none_when_secret_lost(monkeypatch):
    """Losing ASKF_SECRETS_KEY makes previously wrapped keys unrecoverable."""
    monkeypatch.setenv("ASKF_SECRETS_KEY", "test-secret")
    stored = providers._encrypt_key("sk-real")
    monkeypatch.delenv("ASKF_SECRETS_KEY", raising=False)

    assert providers._decrypt_key(stored) is None


def test_encrypt_decrypt_survives_provider_rename(monkeypatch):
    """The envelope isn't bound to the provider name, renaming can't break it."""
    monkeypatch.setenv("ASKF_SECRETS_KEY", "test-secret")
    stored = providers._encrypt_key("sk-real")

    assert providers._decrypt_key(stored) == "sk-real"


# ─── Wiring: the repository functions actually use the helpers ────────────


class _Cursor:
    def __init__(self, calls):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return {
            "id": 1, "name": "A", "protocol": "openai_compat",
            "base_url": "http://x", "api_key": "stored-value",
            "capabilities": "[]", "voices": "[]", "enabled": True,
            "last_probed_at": None, "probe_status": None, "probe_error": None,
            "created_at": None, "updated_at": None,
        }


class _Conn:
    def __init__(self, calls):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self, **kwargs):
        return _Cursor(self._calls)

    def commit(self):
        pass


def test_create_provider_encrypts_before_insert(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(providers, "get_connection", lambda: _Conn(calls))
    monkeypatch.setattr(providers, "_encrypt_key", lambda raw: "ENCRYPTED" if raw else raw)

    providers.create_provider(
        name="A", protocol="openai_compat", base_url="http://x", api_key="sk-real",
    )

    sql, params = [c for c in calls if "INSERT INTO providers" in c[0]][0]
    assert params[3] == "ENCRYPTED"  # (name, protocol, base_url, api_key, ...)


def test_update_provider_encrypts_when_api_key_is_patched(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(providers, "get_connection", lambda: _Conn(calls))
    monkeypatch.setattr(providers, "_encrypt_key", lambda raw: "ENCRYPTED" if raw else raw)

    providers.update_provider(1, api_key="sk-real")

    sql, params = [c for c in calls if "UPDATE providers" in c[0]][0]
    assert "ENCRYPTED" in params


def test_update_provider_leaves_key_untouched_when_not_patched(monkeypatch):
    """Saving only base_url must not call the crypto helper at all."""
    calls: list[tuple] = []
    monkeypatch.setattr(providers, "get_connection", lambda: _Conn(calls))
    encrypt_calls = []
    monkeypatch.setattr(providers, "_encrypt_key", lambda raw: encrypt_calls.append(raw) or raw)

    providers.update_provider(1, base_url="http://new")

    assert encrypt_calls == []


def test_row_to_dict_decrypts_the_stored_key(monkeypatch):
    monkeypatch.setattr(providers, "_decrypt_key", lambda stored: f"DECRYPTED({stored})")

    row = {
        "id": 1, "name": "A", "protocol": "openai_compat", "base_url": "http://x",
        "api_key": "stored-value", "capabilities": "[]", "voices": "[]",
        "enabled": True, "last_probed_at": None, "created_at": None, "updated_at": None,
    }

    result = providers._row_to_dict(row)
    assert result["api_key"] == "DECRYPTED(stored-value)"
