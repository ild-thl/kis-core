"""The access codes in the database."""
from datetime import datetime

import psycopg2.extras

from src.core.db.pool import get_connection


def create_code(
    *,
    code: str,
    label: str,
    role: str,
    custom_role_id: int | None,
    max_uses: int,
    valid_until: datetime,
    access_hours: int | None,
    show_credentials: bool,
    show_evaluation: bool,
    created_by: int,
) -> int:
    """Creates a code and returns its id."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO access_codes
                       (code, label, role, custom_role_id, max_uses,
                        valid_until, access_hours, show_credentials, show_evaluation,
                        created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (code, label, role, custom_role_id, max_uses,
                 valid_until, access_hours, show_credentials, show_evaluation, created_by),
            )
            code_id = cur.fetchone()[0]
        conn.commit()
        return code_id


def list_codes() -> list[dict]:
    """All codes, newest first."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM access_codes ORDER BY created_at DESC")
            return [dict(zeile) for zeile in cur.fetchall()]


def get_code_by_code(code: str) -> dict | None:
    """Looks up a code by the string the user typed."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM access_codes WHERE code = %s", (code,))
            zeile = cur.fetchone()
            return dict(zeile) if zeile else None


def get_code_by_id(code_id: int) -> dict | None:
    """Looks up a code by its numeric id."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM access_codes WHERE id = %s", (code_id,))
            zeile = cur.fetchone()
            return dict(zeile) if zeile else None


def update_code(
    code_id: int,
    *,
    label: str,
    role: str,
    custom_role_id: int | None,
    max_uses: int,
    valid_until: datetime,
    access_hours: int | None,
    show_credentials: bool,
    show_evaluation: bool,
) -> bool:
    """Changes everything about a code except the code string and the used_count."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE access_codes
                       SET label = %s, role = %s, custom_role_id = %s, max_uses = %s,
                           valid_until = %s, access_hours = %s, show_credentials = %s,
                           show_evaluation = %s
                   WHERE id = %s AND %s >= used_count
                   RETURNING id""",
                (label, role, custom_role_id, max_uses, valid_until, access_hours,
                 show_credentials, show_evaluation, code_id, max_uses),
            )
            getroffen = cur.fetchone() is not None
        conn.commit()
        return getroffen


def shows_evaluation(user_id: int) -> bool:
    """Whether this account came from a code that asks its visitors for the evaluation."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM users u
                       JOIN access_codes c ON c.id = u.access_code_id
                   WHERE u.id = %s AND c.show_evaluation""",
                (user_id,),
            )
            return cur.fetchone() is not None


def set_active(code_id: int, active: bool) -> bool:
    """Switches a code on or off, accounts stay untouched."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE access_codes SET active = %s WHERE id = %s RETURNING id",
                (active, code_id),
            )
            getroffen = cur.fetchone() is not None
        conn.commit()
        return getroffen


def delete_code(code_id: int) -> bool:
    """Removes the code, the foreign key empties access_code_id and keeps the accounts."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM access_codes WHERE id = %s RETURNING id", (code_id,))
            getroffen = cur.fetchone() is not None
        conn.commit()
        return getroffen


def claim_use(code_id: int) -> bool:
    """Takes one seat, only while the code is on, valid and not full."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE access_codes SET used_count = used_count + 1
                   WHERE id = %s AND active AND valid_until > NOW()
                     AND used_count < max_uses
                   RETURNING id""",
                (code_id,),
            )
            getroffen = cur.fetchone() is not None
        conn.commit()
        return getroffen


def release_use(code_id: int) -> None:
    """Gives the seat back when creating the account failed afterwards."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE access_codes SET used_count = used_count - 1 "
                "WHERE id = %s AND used_count > 0",
                (code_id,),
            )
        conn.commit()


def lock_expired_accounts() -> int:
    """Switches off every account whose test access ran out, keeps the account itself."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE users SET active = 0
                   WHERE access_code_id IS NOT NULL AND active = 1
                     AND access_expires_at IS NOT NULL AND access_expires_at <= NOW()
                   RETURNING id""",
            )
            gesperrt = cur.fetchall()
        conn.commit()
        return len(gesperrt)


def list_accounts_due_for_deletion(days: int) -> list[int]:
    """Accounts from a code whose deadline passed longer ago than the grace period."""
    if days <= 0:
        return []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM users
                   WHERE access_code_id IS NOT NULL
                     AND access_expires_at IS NOT NULL
                     AND access_expires_at + make_interval(days => %s) <= NOW()
                   ORDER BY id""",
                (days,),
            )
            return [zeile[0] for zeile in cur.fetchall()]


def list_users_for_code(code_id: int) -> list[dict]:
    """Every account a code created, newest first."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """SELECT id, username, created_at, access_expires_at, active
                   FROM users WHERE access_code_id = %s ORDER BY created_at DESC""",
                (code_id,),
            )
            return [dict(zeile) for zeile in cur.fetchall()]


def set_user_access(user_id: int, *, expires_at: datetime | None, code_id: int | None) -> None:
    """Writes the deadline and the origin onto the account."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET access_expires_at = %s, access_code_id = %s WHERE id = %s",
                (expires_at, code_id, user_id),
            )
        conn.commit()


def list_workspaces_for_user(user_id: int) -> list[dict]:
    """Every module this account owns or joined, owned wins where both apply."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """SELECT id AS workspace_id, title, created_at AS since
                   FROM aia_workspaces WHERE user_id = %s""",
                (user_id,),
            )
            eintraege = {zeile["workspace_id"]: {**dict(zeile), "relation": "owner"} for zeile in cur.fetchall()}
            cur.execute(
                """SELECT w.id AS workspace_id, w.title, e.created_at AS since
                   FROM aia_enrollments e JOIN aia_workspaces w ON w.id = e.workspace_id
                   WHERE e.user_id = %s""",
                (user_id,),
            )
            for zeile in cur.fetchall():
                eintraege.setdefault(zeile["workspace_id"], {**dict(zeile), "relation": "enrolled"})
    return sorted(eintraege.values(), key=lambda z: z["since"], reverse=True)


def list_messages_for_user(user_id: int, limit: int = 50) -> list[dict]:
    """This account's chat rounds across every module, newest first and capped so the query stays cheap."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """SELECT m.role, m.content, m.created_at, m.failed, m.aborted,
                          w.title AS workspace_title
                   FROM aia_messages m
                   JOIN aia_workspaces w ON w.id = m.workspace_id
                   WHERE m.user_id = %s
                   ORDER BY m.created_at DESC
                   LIMIT %s""",
                (user_id, limit),
            )
            return [dict(zeile) for zeile in cur.fetchall()]


def set_code_workspaces(code_id: int, workspace_ids: list[int]) -> None:
    """Replaces the workspaces a code enrolls into, unknown ids simply drop out."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM access_code_workspaces WHERE code_id = %s", (code_id,))
            if workspace_ids:
                cur.execute(
                    """INSERT INTO access_code_workspaces (code_id, workspace_id)
                       SELECT %s, id FROM aia_workspaces WHERE id = ANY(%s)""",
                    (code_id, list(workspace_ids)),
                )
        conn.commit()


def workspaces_by_code() -> dict[int, list[dict]]:
    """Every code's workspaces with title and owner, for the list in one query."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """SELECT cw.code_id, w.id, w.title, w.user_id AS owner_id,
                          COALESCE(NULLIF(u.display_name, ''), u.username) AS owner_name
                   FROM access_code_workspaces cw
                   JOIN aia_workspaces w ON w.id = cw.workspace_id
                   LEFT JOIN users u ON u.id = w.user_id
                   ORDER BY w.title"""
            )
            ergebnis: dict[int, list[dict]] = {}
            for zeile in cur.fetchall():
                eintrag = dict(zeile)
                ergebnis.setdefault(eintrag.pop("code_id"), []).append(eintrag)
            return ergebnis


def custom_role_ids_with(permission: str) -> list[int]:
    """The custom roles that hold this permission."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM custom_roles WHERE permissions ? %s", (permission,))
            return [zeile[0] for zeile in cur.fetchall()]


def search_workspace_owners(
    *,
    query: str,
    user_ids: list[int],
    system_roles: list[str],
    custom_role_ids: list[int],
    admin_email: str,
    limit: int,
) -> list[dict]:
    """Real accounts with the given rights that own workspaces, found by name, username or workspace title, or by id."""
    muster = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """WITH treffer AS (
                       SELECT u.id, LOWER(COALESCE(NULLIF(u.display_name, ''), u.username)) AS sortname
                       FROM users u
                       WHERE NOT u.is_demo
                         AND EXISTS (SELECT 1 FROM aia_workspaces w WHERE w.user_id = u.id)
                         AND (u.role = ANY(%(rollen)s)
                              OR (u.role = 'custom' AND u.custom_role_id = ANY(%(eigene)s))
                              OR (%(admin)s <> '' AND LOWER(u.email) = %(admin)s))
                         AND (u.id = ANY(%(ids)s)
                              OR (%(q)s <> '' AND (
                                  COALESCE(u.display_name, '') ILIKE %(muster)s
                                  OR u.username ILIKE %(muster)s
                                  OR EXISTS (SELECT 1 FROM aia_workspaces w
                                             WHERE w.user_id = u.id AND w.title ILIKE %(muster)s))))
                       ORDER BY sortname
                       LIMIT %(limit)s
                   )
                   SELECT u.id AS user_id, u.role,
                          COALESCE(NULLIF(u.display_name, ''), u.username) AS name,
                          u.username AS username,
                          w.id AS workspace_id, w.title
                   FROM treffer t
                   JOIN users u ON u.id = t.id
                   JOIN aia_workspaces w ON w.user_id = u.id
                   ORDER BY t.sortname, LOWER(w.title)""",
                {
                    "rollen": list(system_roles),
                    "eigene": list(custom_role_ids),
                    "admin": admin_email,
                    "ids": list(user_ids),
                    "q": query,
                    "muster": muster,
                    "limit": limit,
                },
            )
            besitzer: dict[int, dict] = {}
            for zeile in cur.fetchall():
                eintrag = besitzer.setdefault(zeile["user_id"], {
                    "user_id": zeile["user_id"],
                    "name": zeile["name"],
                    "username": zeile["username"],
                    "role": zeile["role"],
                    "workspaces": [],
                })
                eintrag["workspaces"].append({"id": zeile["workspace_id"], "title": zeile["title"]})
            return list(besitzer.values())


def enroll_into_code_workspaces(code_id: int, user_ids: list[int]) -> int:
    """Enrolls these accounts as learners in every workspace of the code, the owner itself is skipped."""
    if not user_ids:
        return 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO aia_enrollments (workspace_id, user_id, role)
                   SELECT cw.workspace_id, konto.id, 'student'
                   FROM access_code_workspaces cw
                   JOIN aia_workspaces w ON w.id = cw.workspace_id
                   CROSS JOIN UNNEST(%s::int[]) AS konto(id)
                   WHERE cw.code_id = %s AND w.user_id <> konto.id
                   ON CONFLICT (workspace_id, user_id) DO NOTHING""",
                (list(user_ids), code_id),
            )
            anzahl = cur.rowcount
        conn.commit()
        return anzahl


def list_user_ids_for_code(code_id: int) -> list[int]:
    """The ids of every account a code created."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE access_code_id = %s", (code_id,))
            return [zeile[0] for zeile in cur.fetchall()]


def set_users_active(user_ids: list[int], active: bool) -> list[int]:
    """Switches the login of these code accounts on or off, other accounts are never touched."""
    if not user_ids:
        return []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE users SET active = %s
                   WHERE id = ANY(%s) AND access_code_id IS NOT NULL
                   RETURNING id""",
                (1 if active else 0, list(user_ids)),
            )
            getroffen = [zeile[0] for zeile in cur.fetchall()]
        conn.commit()
        return getroffen
