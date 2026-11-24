# backend/src/permissions.py
"""Permission model: a person holds a set of keys from the catalogue."""
from dataclasses import dataclass, field

from src.modules import active_modules
from src.permissions_registry import (
    PERM_AIA_USE,
    PERM_AIA_WORKSPACE_CREATE,
    PERM_SET_USERS_ALL,
    SYSTEM_ROLE_PERMISSIONS,
    SYSTEM_ROLES,
    TOOL_KEYS,
    is_settings_key,
    keys_for_modules,
    tool_key_of,
    valid_keys,
)

__all__ = [
    "SYSTEM_ROLES",
    "Permissions",
    "permissions_for_system_role",
    "resolve_user_permissions",
    "custom_role_permissions",
]


@dataclass(frozen=True)
class Permissions:
    """What someone may do, as a set of keys."""

    keys: frozenset[str] = field(default_factory=frozenset)
    allow_account_create: bool = False

    def has(self, *keys: str) -> bool:
        """True as soon as one of the named keys is present."""
        return any(k in self.keys for k in keys)

    # --- derived view for everything still using the old names --------
    @property
    def allow_admin_panel(self) -> bool:
        """May see any page of the area at all."""
        return any(is_settings_key(k) for k in self.keys)

    @property
    def allow_aia(self) -> bool:
        return PERM_AIA_USE in self.keys

    @property
    def allow_workspace_create(self) -> bool:
        return PERM_AIA_WORKSPACE_CREATE in self.keys

    @property
    def tools(self) -> tuple[str, ...]:
        """Tool keys without a prefix, in catalogue order."""
        return tuple(tool_key_of(k) for k in TOOL_KEYS if k in self.keys)

    @property
    def settings_pages(self) -> tuple[str, ...]:
        return tuple(k for k in sorted(self.keys) if is_settings_key(k))


def permissions_for_system_role(role: str, modules=None) -> Permissions:
    preset = SYSTEM_ROLE_PERMISSIONS.get(role)
    if preset is None:
        raise ValueError(f"Unknown system role: {role!r}")
    erlaubt = set(keys_for_modules(modules if modules is not None else active_modules()))
    return Permissions(keys=frozenset(k for k in preset if k in erlaubt))


def custom_role_permissions(keys, modules=None) -> Permissions:
    """Permissions of a custom role from the database, unknown ones are dropped."""
    erlaubt = set(keys_for_modules(modules if modules is not None else active_modules()))
    return Permissions(keys=frozenset(k for k in valid_keys(keys) if k in erlaubt))


def is_full_admin(perms: Permissions, modules=None) -> bool:
    """Holds every settings page of the active catalogue, the frontend measures the same way."""
    erlaubt = keys_for_modules(modules if modules is not None else active_modules())
    return all(k in perms.keys for k in erlaubt if is_settings_key(k))


def resolve_user_permissions(
    role: str,
    custom_role_id: int | None,
    is_env_admin: bool,
) -> Permissions:
    """Computes the effective permissions, creating accounts comes with user administration."""
    base = _resolve_base_permissions(role, custom_role_id, is_env_admin)
    if PERM_SET_USERS_ALL in base.keys:
        return Permissions(keys=base.keys, allow_account_create=True)
    return base


def _resolve_base_permissions(
    role: str,
    custom_role_id: int | None,
    is_env_admin: bool,
) -> Permissions:
    """The base permissions before the account creation switch, the environment admin always wins."""
    if is_env_admin:
        return permissions_for_system_role("admin")
    if role in SYSTEM_ROLES:
        return permissions_for_system_role(role)
    if role == "custom" and custom_role_id is not None:
        # Lazy import to avoid pulling psycopg2 at module import time.
        from src import database
        cr = database.get_custom_role(custom_role_id)
        if cr is None:
            # Custom role was deleted concurrently; degrade gracefully to 'user'.
            return permissions_for_system_role("user")
        return custom_role_permissions(cr["permissions"])
    # Unknown / corrupt role -> safest fallback
    return permissions_for_system_role("user")
