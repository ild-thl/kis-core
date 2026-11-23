import hashlib
import hmac

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Settings from the environment, without provider credentials."""

    # Signs the session cookies, derived from kis_secrets_key when left empty.
    session_secret: str = ""

    # Master secret that encrypts provider API keys, see services/export_crypto.py.
    kis_secrets_key: str = ""

    # The admin account, written onto the row on every start.
    admin_username: str = ""
    admin_email: str = ""

    # The admin's password, only read on start and never written back.
    admin_password: str = ""

    # Set via start-nginx.sh / start-th.sh, never in .env
    production: bool = False

    # Unlocks invitations, access codes and creating accounts by hand.
    account_creation_enabled: bool = False

    # No login screen at all, everybody is the local admin. Local use only.
    auth_disabled: bool = False

    # Which halves this installation has, comma separated from "aia" and "tools".
    modules: str = "aia,tools"

    # Key used to encrypt provider credentials on read and write.
    kis_export_key: str = ""

    @model_validator(mode="after")
    def _derive_session_secret(self) -> "Settings":
        # Derive instead of reusing the master secret so a leaked cookie key reveals nothing about it.
        if not self.session_secret and self.kis_secrets_key.strip():
            self.session_secret = hmac.new(
                self.kis_secrets_key.strip().encode("utf-8"), b"kis-session", hashlib.sha256
            ).hexdigest()
        return self

    @property
    def is_local_mode(self) -> bool:
        return self.auth_disabled

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "populate_by_name": True}
