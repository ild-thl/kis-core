from datetime import datetime

import psycopg2.extras

from src.core.db.pool import get_connection

from .access_links import get_workspace_by_access_link_code


def enroll_student(
    workspace_id: int, user_id: int, enrolled_until: datetime | None,
    link_id: int | None = None, role: str = "student", via_demo: bool = False,
) -> int | None:
    """Enrolls a person, or None when they are already enrolled."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO aia_enrollments
                          (workspace_id, user_id, link_id, enrolled_until, role, via_demo)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (workspace_id, user_id) DO NOTHING
                   RETURNING id""",
                (workspace_id, user_id, link_id, enrolled_until, role, via_demo),
            )
            row = cur.fetchone()
        conn.commit()
    return row[0] if row else None

def delete_demo_enrollment(workspace_id: int, user_id: int) -> bool:
    """Deletes only an enrollment created through the demo, never a real one."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM aia_enrollments "
                "WHERE workspace_id = %s AND user_id = %s AND via_demo",
                (workspace_id, user_id),
            )
            geloescht = cur.rowcount > 0
        conn.commit()
    return geloescht

def delete_demo_enrollments_of_owner(owner_id: int) -> int:
    """Clears all demo enrollments in the courses of this account."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """DELETE FROM aia_enrollments e
                    USING aia_workspaces m
                    WHERE e.workspace_id = m.id AND m.user_id = %s AND e.via_demo""",
                (owner_id,),
            )
            anzahl = cur.rowcount
        conn.commit()
    return anzahl

def is_workspace_tutor(workspace_id: int, user_id: int) -> bool:
    """True when the person came through a tutor link, expired ones included."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM aia_enrollments "
                "WHERE workspace_id = %s AND user_id = %s AND role = 'tutor'",
                (workspace_id, user_id),
            )
            return cur.fetchone() is not None

def get_workspace_participants(workspace_id: int) -> list[dict]:
    """All enrolled people, one entry per person, the strongest role wins."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """SELECT e.user_id,
                          u.display_name,
                          u.username,
                          BOOL_OR(e.role = 'tutor') AS is_tutor,
                          MIN(e.created_at)         AS joined_at,
                          MAX(e.enrolled_until)     AS enrolled_until
                   FROM aia_enrollments e
                   JOIN users u ON u.id = e.user_id
                   WHERE e.workspace_id = %s
                   GROUP BY e.user_id, u.display_name, u.username
                   ORDER BY BOOL_OR(e.role = 'tutor') DESC, u.display_name ASC""",
                (workspace_id,),
            )
            rows = cur.fetchall()
    return [dict(row) for row in rows]


def set_participant_role(workspace_id: int, user_id: int, role: str) -> int:
    """Promotes or demotes, all enrollments of the person move along."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE aia_enrollments SET role = %s WHERE workspace_id = %s AND user_id = %s",
                (role, workspace_id, user_id),
            )
            geaendert = cur.rowcount
        conn.commit()
    return geaendert


def count_enrollments(workspace_id: int) -> int:
    """How many people are currently enrolled, tutors included."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM aia_enrollments WHERE workspace_id = %s",
                (workspace_id,),
            )
            return cur.fetchone()[0]

def is_student_enrolled(workspace_id: int, user_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM aia_enrollments WHERE workspace_id = %s AND user_id = %s",
                (workspace_id, user_id),
            )
            return cur.fetchone() is not None

def get_enrollment(workspace_id: int, user_id: int, link_id: int | None = None) -> dict | None:
    """Get a specific enrollment by workspace, user, and optionally link."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            if link_id is not None:
                cur.execute(
                    "SELECT * FROM aia_enrollments WHERE workspace_id = %s AND user_id = %s AND link_id = %s",
                    (workspace_id, user_id, link_id),
                )
            else:
                cur.execute(
                    "SELECT * FROM aia_enrollments WHERE workspace_id = %s AND user_id = %s ORDER BY created_at DESC LIMIT 1",
                    (workspace_id, user_id),
                )
            row = cur.fetchone()
    return dict(row) if row else None

def get_workspace_by_enroll_code(code: str) -> dict | None:
    """Legacy: check both access_links and workspaces table."""
    result = get_workspace_by_access_link_code(code)
    if result:
        return result[0]  # return just the workspace for backward compat
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """SELECT * FROM aia_workspaces
                   WHERE enroll_code = %s AND enroll_code_expires > NOW()""",
                (code,),
            )
            row = cur.fetchone()
    return dict(row) if row else None

