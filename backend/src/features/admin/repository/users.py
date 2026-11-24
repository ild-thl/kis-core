from datetime import datetime

import psycopg2.extras

from src.core.db._common import _de_date_to_utc
from src.core.db.pool import get_connection


def get_user_by_username(username: str):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            return cur.fetchone()

def get_user_by_id(user_id: int):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return cur.fetchone()

def get_user_by_email(email: str):
    """Finds the account by its mail address, an empty address matches nobody."""
    wert = (email or "").strip()
    if not wert:
        return None
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT * FROM users WHERE LOWER(email) = LOWER(%s) ORDER BY id LIMIT 1",
                (wert,),
            )
            return cur.fetchone()


def create_user(
    username: str,
    display_name: str,
    email: str | None,
    active: int,
    role: str = "user",
    password_hash: str | None = None,
) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, display_name, email, active, role, password_hash) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (username, display_name, email or None, active, role, password_hash),
            )
            user_id = cur.fetchone()[0]
        conn.commit()
        return user_id

def update_user(user_id: int, display_name: str, email: str, active: int) -> None:
    """Changes the profile fields, the role goes through set_user_role."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET display_name = %s, email = %s, active = %s WHERE id = %s",
                (display_name, email, active, user_id),
            )
        conn.commit()


def update_user_locale(user_id: int, locale: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET locale = %s WHERE id = %s", (locale, user_id))
        conn.commit()


# --- Whitelist ---

def get_whitelist_emails() -> list[str]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT email FROM whitelist ORDER BY created_at")
            rows = cur.fetchall()
        return [row["email"] for row in rows]

def add_to_whitelist(email: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO whitelist (email) VALUES (%s) ON CONFLICT DO NOTHING",
                (email.strip().lower(),),
            )
        conn.commit()

def remove_from_whitelist(email: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM whitelist WHERE LOWER(email) = LOWER(%s)", (email.strip(),))
        conn.commit()

def get_all_users(
    limit: int = 50, offset: int = 0, q: str = "",
    date_from: str = "", date_to: str = "",
) -> tuple[list[dict], int]:
    """All users, newest first, as a pair of list and total count."""
    conditions = []
    params: list = []

    if q:
        like = f"%{q}%"
        conditions.append("(display_name ILIKE %s OR username ILIKE %s OR email ILIKE %s)")
        params += [like, like, like]
    if date_from:
        conditions.append("created_at >= %s::timestamp")
        params.append(_de_date_to_utc(date_from))
    if date_to:
        conditions.append("created_at <= %s::timestamp")
        params.append(_de_date_to_utc(date_to, end_of_day=True))

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                f"SELECT * FROM users {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                params + [limit, offset],
            )
            rows = cur.fetchall()
            cur.execute(f"SELECT COUNT(*) AS total FROM users {where}", params)
            total = cur.fetchone()["total"]
    return [dict(row) for row in rows], total

def get_pending_users() -> list[dict]:
    """Users with active=0, waiting for an admin to activate them."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE active = 0 ORDER BY created_at DESC")
            rows = cur.fetchall()
        return [dict(row) for row in rows]

def activate_user(user_id: int) -> None:
    """Set active=1 for the given user."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET active = 1 WHERE id = %s", (user_id,))
        conn.commit()


def set_user_password(user_id: int, password_hash: str | None) -> None:
    """Sets the hash, None takes the form login away from the account."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id)
            )
        conn.commit()

def set_user_demo(user_id: int, is_demo: bool) -> list[int]:
    """Sets exactly one demo account and reports who lost the flag doing so."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if is_demo:
                cur.execute(
                    "UPDATE users SET is_demo = (id = %s) WHERE is_demo OR id = %s "
                    "RETURNING id, is_demo",
                    (user_id, user_id),
                )
                verloren = [zeile[0] for zeile in cur.fetchall() if not zeile[1]]
            else:
                cur.execute(
                    "UPDATE users SET is_demo = FALSE WHERE id = %s AND is_demo RETURNING id",
                    (user_id,),
                )
                verloren = [zeile[0] for zeile in cur.fetchall()]
        conn.commit()
    return verloren

def deactivate_user_by_email(email: str) -> None:
    """Set active=0 for any user with the given email."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET active = 0 WHERE LOWER(email) = LOWER(%s)", (email.strip(),)
            )
        conn.commit()


def ensure_local_admin() -> int:
    """Create the local admin user if it doesn't exist yet. Returns user_id."""
    existing = get_user_by_username("local")
    if existing:
        return existing["id"]
    return create_user(
        username="local",
        display_name="Admin",
        email="",
        active=1,
        role="admin",
    )


def set_user_tour_seen(user_id: int, seen: bool) -> None:
    """Marks the tour as done, or releases it again so the invitation returns."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET tour_seen_at = %s WHERE id = %s",
                (datetime.now() if seen else None, user_id),
            )
        conn.commit()


def get_global_consent(user_id: int) -> dict:
    """When and which version of the global notice this person accepted, both None when never."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT global_consent_at, global_consent_version FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
    if not row:
        return {"global_consent_at": None, "global_consent_version": None}
    return dict(row)


def set_global_consent(user_id: int, version: int) -> None:
    """Notes the acceptance with the current time, same account for TH, external or demo access."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET global_consent_at = NOW(), global_consent_version = %s WHERE id = %s",
                (version, user_id),
            )
        conn.commit()
