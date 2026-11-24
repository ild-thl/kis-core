"""Login sessions in Redis so they survive a restart and several processes."""

import hashlib
import hmac
import json
import secrets

from loguru import logger
from src.core.redis_url import REDIS_URL

_KEY_PREFIX = "askf:session:"


class SessionStore:
    def __init__(self, secret: str, max_age: int = 86400):
        self._secret = secret.encode()
        self._max_age = max_age
        self._client = None

    # ─── intern ──────────────────────────────────────────────────────────────

    def _redis(self):
        """Client with short timeouts, same pattern as rate_limit.py."""
        if self._client is None:
            import redis as _redis_lib
            self._client = _redis_lib.from_url(
                REDIS_URL, socket_connect_timeout=1, socket_timeout=1
            )
        return self._client

    def _sign(self, data: str) -> str:
        sig = hmac.new(self._secret, data.encode(), hashlib.sha256).hexdigest()
        return f"{data}.{sig}"

    def _verify(self, token: str) -> str | None:
        parts = token.rsplit(".", 1)
        if len(parts) != 2:
            return None
        data, sig = parts
        expected = hmac.new(self._secret, data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return data

    # ─── public ──────────────────────────────────────────────────────────────

    def create(self, data: dict | None = None) -> str:
        raw_id = secrets.token_hex(32)
        token = self._sign(raw_id)
        # Redis handles the expiry itself, absolute from creation.
        self._redis().set(
            _KEY_PREFIX + raw_id, json.dumps(data or {}), ex=self._max_age
        )
        return token

    def get_data(self, token: str) -> dict | None:
        raw_id = self._verify(token)
        if raw_id is None:
            return None
        try:
            raw = self._redis().get(_KEY_PREFIX + raw_id)
        except Exception as e:
            logger.error("Session read failed (Redis): {}", e)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            logger.error("Session payload is not valid JSON, treating as absent")
            return None

    def validate(self, token: str) -> bool:
        raw_id = self._verify(token)
        if raw_id is None:
            return False
        try:
            return bool(self._redis().exists(_KEY_PREFIX + raw_id))
        except Exception as e:
            # Fail closed, siehe Modulkommentar.
            logger.error("Session check failed (Redis), rejecting: {}", e)
            return False

    def destroy(self, token: str) -> None:
        raw_id = self._verify(token)
        if raw_id is None:
            return
        try:
            self._redis().delete(_KEY_PREFIX + raw_id)
        except Exception as e:
            logger.error("Session delete failed (Redis): {}", e)

    def destroy_for_users(self, user_ids: list[int]) -> int:
        """Ends every session that belongs to one of these accounts and returns how many."""
        ziele = set(user_ids)
        if not ziele:
            return 0
        beendet = 0
        try:
            client = self._redis()
            for key in client.scan_iter(match=_KEY_PREFIX + "*", count=500):
                raw = client.get(key)
                if raw is None:
                    continue
                try:
                    user_id = json.loads(raw).get("user_id")
                except (ValueError, AttributeError):
                    continue
                if user_id in ziele:
                    client.delete(key)
                    beendet += 1
        except Exception as e:
            logger.error("Session sweep failed (Redis): {}", e)
        return beendet
