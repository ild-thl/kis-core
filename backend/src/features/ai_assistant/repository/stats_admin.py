"""Usage numbers of the learning assistant for admins and workspace owners."""

from psycopg2.extras import RealDictCursor

from src.core.db.pool import get_connection


def _accuracy(correct: int, answers: int) -> int:
    return round(correct / answers * 100) if answers > 0 else 0


def _chat_count(cur, interval: str, workspace_id: int, user_id: int | None = None) -> int:
    """Questions asked in a workspace within the window, optionally of one person."""
    person = " AND user_id = %s" if user_id is not None else ""
    cur.execute(
        f"""SELECT COUNT(*) AS cnt FROM aia_messages
            WHERE workspace_id = %s{person} AND role = 'user'
              AND created_at >= NOW() - INTERVAL %s""",
        (workspace_id, *((user_id,) if user_id is not None else ()), interval),
    )
    return cur.fetchone()["cnt"]


def _student_stats(cur, workspace_id: int, student: dict, interval: str,
                   mode_filter: str, mode_params: tuple) -> dict:
    """Answers and chat questions of one enrolled person in one workspace."""
    cur.execute(
        f"""SELECT COUNT(p.id) AS answers,
                   COUNT(p.id) FILTER (WHERE p.correct) AS correct_cnt,
                   COUNT(p.id) FILTER (WHERE s.mode = 'source') AS lerntools,
                   COUNT(p.id) FILTER (WHERE s.mode = 'glossary') AS language_training
            FROM aia_exercise_progress p
            JOIN aia_exercise_sets s ON s.id = p.set_id
            WHERE s.workspace_id = %s AND p.user_id = %s
              AND p.answered_at >= NOW() - INTERVAL %s{mode_filter}""",
        (workspace_id, student["user_id"], interval, *mode_params),
    )
    ex = cur.fetchone()
    return {
        "name": student["display_name"] or student["username"] or "Unbekannt",
        "answers": ex["answers"],
        "correct": ex["correct_cnt"],
        "accuracy": _accuracy(ex["correct_cnt"], ex["answers"]),
        "lerntools": ex["lerntools"],
        "language_training": ex["language_training"],
        "chat_messages": _chat_count(cur, interval, workspace_id, student["user_id"]),
    }


def _workspace_stats(cur, m: dict, interval: str, mode_filter: str, mode_params: tuple) -> dict:
    """One workspace row of the admin table, with its owner's activity and its students."""
    mid = m["id"]
    owner_id = m["owner_id"]
    lecturer_messages = _chat_count(cur, interval, mid, owner_id)

    cur.execute(
        f"""SELECT COUNT(p.id) AS attempts
            FROM aia_exercise_progress p
            JOIN aia_exercise_sets s ON s.id = p.set_id
            WHERE s.workspace_id = %s AND p.user_id = %s
              AND p.answered_at >= NOW() - INTERVAL %s{mode_filter}""",
        (mid, owner_id, interval, *mode_params),
    )
    lecturer_exercises = cur.fetchone()["attempts"]

    cur.execute(
        f"""SELECT COUNT(p.id) AS total_answers,
                   COUNT(p.id) FILTER (WHERE p.correct) AS total_correct
            FROM aia_exercise_progress p
            JOIN aia_exercise_sets s ON s.id = p.set_id
            WHERE s.workspace_id = %s AND p.answered_at >= NOW() - INTERVAL %s{mode_filter}""",
        (mid, interval, *mode_params),
    )
    ex_row = cur.fetchone()
    chat_cnt = _chat_count(cur, interval, mid)

    cur.execute(
        """SELECT DISTINCT u.id AS user_id,
                  u.display_name, u.username
           FROM aia_enrollments e
           JOIN users u ON e.user_id = u.id
           WHERE e.workspace_id = %s
           ORDER BY u.display_name""",
        (mid,),
    )
    enrolled = [dict(r) for r in cur.fetchall()]

    return {
        "workspace_uuid": m["uuid"],
        "title": m["title"],
        "owner": m["owner_name"] or m["owner_username"] or "Unbekannt",
        "is_active": m["is_active"],
        "source_count": m["source_count"],
        "enrollment_count": m["enrollment_count"],
        "total_answers": ex_row["total_answers"],
        "accuracy": _accuracy(ex_row["total_correct"], ex_row["total_answers"]),
        "chat_messages": chat_cnt,
        "lecturer": {
            "messages": lecturer_messages,
            "exercises": lecturer_exercises,
        },
        "students": [_student_stats(cur, mid, st, interval, mode_filter, mode_params)
                     for st in enrolled],
    }


def get_aia_admin_stats(days: int = 30, mode: str | None = None) -> dict:
    """Numbers of the AI tutor for the admin area."""
    interval = f"{days} days"
    # The mode filter needs the join with aia_exercise_sets as s.
    mode_filter = ""
    mode_params: tuple = ()
    if mode in ("source", "glossary"):
        mode_filter = " AND s.mode = %s"
        mode_params = (mode,)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM aia_workspaces")
            total_workspaces = cur.fetchone()["cnt"]

            cur.execute(
                f"""SELECT COUNT(DISTINCT p.user_id) AS active_students, COUNT(*) AS total_answers
                    FROM aia_exercise_progress p
                    JOIN aia_exercise_sets s ON s.id = p.set_id
                    WHERE p.answered_at >= NOW() - INTERVAL %s{mode_filter}""",
                (interval, *mode_params),
            )
            answers_row = cur.fetchone()

            cur.execute(
                """SELECT COUNT(*) AS cnt FROM aia_messages
                   WHERE role = 'user' AND created_at >= NOW() - INTERVAL %s""",
                (interval,),
            )
            total_chat_messages = cur.fetchone()["cnt"]

            cur.execute(
                """SELECT m.id, m.uuid, m.title, m.is_active, m.user_id AS owner_id,
                          u.display_name AS owner_name, u.username AS owner_username,
                          (SELECT COUNT(*) FROM aia_enrollments e WHERE e.workspace_id = m.id) AS enrollment_count,
                          (SELECT COUNT(DISTINCT src.id) FROM aia_sources src WHERE src.workspace_id = m.id) AS source_count
                   FROM aia_workspaces m
                   JOIN users u ON m.user_id = u.id
                   ORDER BY m.created_at DESC""",
            )
            workspaces_raw = [dict(r) for r in cur.fetchall()]
            workspace_stats = [_workspace_stats(cur, m, interval, mode_filter, mode_params)
                               for m in workspaces_raw]

    return {
        "summary": {
            "total_workspaces": total_workspaces,
            "active_students": answers_row["active_students"],
            "total_answers": answers_row["total_answers"],
            "total_chat_messages": total_chat_messages,
        },
        "workspace_stats": workspace_stats,
        "days": days,
        "mode": mode,
    }


def get_aia_workspace_stats(workspace_id: int) -> dict:
    """Statistics for a single workspace - used by the workspace owner (Lecturer)."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT user_id) AS cnt FROM aia_enrollments WHERE workspace_id = %s",
                (workspace_id,),
            )
            total_enrolled = cur.fetchone()["cnt"]

            cur.execute(
                """SELECT COUNT(DISTINCT user_id) AS cnt
                   FROM aia_messages
                   WHERE workspace_id = %s AND role = 'user'
                     AND created_at >= NOW() - INTERVAL '30 days'""",
                (workspace_id,),
            )
            active_30d = cur.fetchone()["cnt"]

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM aia_messages WHERE workspace_id = %s AND role = 'user'",
                (workspace_id,),
            )
            total_chat = cur.fetchone()["cnt"]

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM aia_exercise_sets WHERE workspace_id = %s",
                (workspace_id,),
            )
            total_sets = cur.fetchone()["cnt"]

    return {
        "overview": {
            "total_enrolled": total_enrolled,
            "active_30d": active_30d,
            "total_chat_messages": total_chat,
            "total_exercise_sets": total_sets,
        },
    }
