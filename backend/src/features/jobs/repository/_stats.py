"""Admin dashboard statistics and activity log."""
from ._shared import psycopg2, get_connection
from ._counts import messpunkt


def get_job_stats(days: int = 30) -> dict:
    """Aggregated job statistics for the admin dashboard."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # 1. Jobs per tool + status
            cur.execute("""
                SELECT tool, status, COUNT(*) AS cnt
                FROM jobs
                WHERE created_at >= NOW() - make_interval(days => %s)
                GROUP BY tool, status
                ORDER BY tool, status
            """, (days,))
            by_tool_status = [dict(r) for r in cur.fetchall()]

            # 2. Jobs per day (last N days)
            cur.execute("""
                SELECT (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Berlin')::date AS day,
                       COUNT(*) AS cnt
                FROM jobs
                WHERE created_at >= NOW() - make_interval(days => %s)
                GROUP BY day ORDER BY day
            """, (days,))
            by_day = [{"day": str(r["day"]), "count": r["cnt"]} for r in cur.fetchall()]

            # 3. Top users
            cur.execute("""
                SELECT u.display_name, u.username, COUNT(*) AS cnt
                FROM jobs j
                JOIN users u ON j.user_id = u.id
                WHERE j.created_at >= NOW() - make_interval(days => %s)
                GROUP BY u.display_name, u.username
                ORDER BY cnt DESC LIMIT 10
            """, (days,))
            top_users = [
                {"name": r["display_name"] or r["username"], "count": r["cnt"]}
                for r in cur.fetchall()
            ]

            # For a screencast only the render time counts, without preparation.
            cur.execute("""
                SELECT tool,
                       ROUND(AVG(EXTRACT(EPOCH FROM (
                           completed_at - COALESCE(
                               CASE WHEN tool IN (
                                   'screencast_render', 'screencast_translate'
                               ) THEN render_started_at END,
                               started_at
                           )
                       )))::numeric, 1) AS avg_sec
                FROM jobs
                WHERE status = 'success' AND completed_at IS NOT NULL
                  AND COALESCE(
                      CASE WHEN tool IN (
                          'screencast_render', 'screencast_translate'
                      ) THEN render_started_at END,
                      started_at
                  ) IS NOT NULL
                  AND created_at >= NOW() - make_interval(days => %s)
                GROUP BY tool ORDER BY tool
            """, (days,))
            avg_duration = {r["tool"]: float(r["avg_sec"]) for r in cur.fetchall()}

    return {
        "by_tool_status": by_tool_status,
        "by_day": by_day,
        "top_users": top_users,
        "avg_duration": avg_duration,
    }


def get_job_activity_log(days: int = 30, limit: int = 50) -> list[dict]:
    """Recent job activity for admin dashboard - chronological log."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT j.tool, j.status, j.created_at, j.completed_at,
                          j.started_at, j.render_started_at, j.original_filename,
                          u.display_name, u.username
                   FROM jobs j
                   JOIN users u ON j.user_id = u.id
                   WHERE j.created_at >= NOW() - make_interval(days => %s)
                   ORDER BY j.created_at DESC
                   LIMIT %s""",
                (days, limit),
            )
            rows = []
            for r in cur.fetchall():
                duration_sec = None
                beginn = messpunkt(r["tool"], r["started_at"], r["render_started_at"])
                if r["status"] == "success" and r["completed_at"] and beginn:
                    duration_sec = (r["completed_at"] - beginn).total_seconds()

                rows.append({
                    "user": r["display_name"] or r["username"] or "Unbekannt",
                    "tool": r["tool"],
                    "status": r["status"],
                    "filename": r["original_filename"],
                    "created_at": r["created_at"].isoformat() + "Z" if r["created_at"] else None,
                    "duration_seconds": round(duration_sec, 1) if duration_sec is not None else None,
                })
    return rows
