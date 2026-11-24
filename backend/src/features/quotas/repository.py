from typing import Optional

import psycopg2.extras

from src.core.db.pool import get_connection


def quota_get_override(user_id: int, quota_type: str) -> Optional[int]:
    """Return per-user override limit, or None if no override exists."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT limit_value FROM user_quota_overrides WHERE user_id = %s AND quota_type = %s",
                (user_id, quota_type),
            )
            row = cur.fetchone()
    return row[0] if row else None

def quota_set_override(user_id: int, quota_type: str, limit_value: int) -> None:
    """Upsert a per-user override. limit_value=-1 means unlimited."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_quota_overrides (user_id, quota_type, limit_value)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (user_id, quota_type)
                   DO UPDATE SET limit_value = EXCLUDED.limit_value, updated_at = NOW()""",
                (user_id, quota_type, limit_value),
            )
        conn.commit()

def quota_remove_override(user_id: int, quota_type: str) -> None:
    """Remove a per-user override so the user falls back to the global default."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_quota_overrides WHERE user_id = %s AND quota_type = %s",
                (user_id, quota_type),
            )
        conn.commit()

def quota_reset(user_id: int, quota_type: str) -> None:
    """Admin: immediately zero a user's quota counter and end its window."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE user_quotas
                   SET used = 0, window_started_at = NULL, reset_at = NULL, updated_at = NOW()
                   WHERE user_id = %s AND quota_type = %s""",
                (user_id, quota_type),
            )
        conn.commit()

def quota_get_all_for_user(user_id: int) -> list[dict]:
    """Return all quota rows for a user (used, reset_at, override if any)."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """SELECT
                     COALESCE(q.quota_type, o.quota_type) AS quota_type,
                     COALESCE(q.used, 0)                  AS used,
                     q.reset_at,
                     o.limit_value                        AS override
                   FROM user_quotas q
                   FULL OUTER JOIN user_quota_overrides o
                     ON o.user_id = q.user_id AND o.quota_type = q.quota_type
                   WHERE COALESCE(q.user_id, o.user_id) = %s""",
                (user_id,),
            )
            rows = cur.fetchall()
    return [dict(row) for row in rows]

def quota_get_all_users_usage() -> list[dict]:
    """Admin: return all active users with quota data (used=0 if no activity yet)."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """SELECT u.id AS user_id, u.username, u.display_name,
                          q.quota_type, COALESCE(q.used, 0) AS used, q.reset_at,
                          o.limit_value AS override
                   FROM users u
                   LEFT JOIN user_quotas q ON q.user_id = u.id
                   LEFT JOIN user_quota_overrides o
                     ON o.user_id = u.id AND o.quota_type = q.quota_type
                   WHERE u.active = 1
                   ORDER BY u.display_name, q.quota_type"""
            )
            rows = cur.fetchall()
    return [dict(row) for row in rows]
