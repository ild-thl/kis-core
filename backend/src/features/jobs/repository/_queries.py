"""Read-only queries, lists and counts on the jobs table."""
from ._shared import psycopg2, get_connection, _notify_job_update, _de_date_to_utc

# Services that wait on the voice provider count apart, so a voicing never holds up a service without one.
VOICE_TOOLS = frozenset({"tts", "podcast", "screencast_translate", "screencast_render"})


def get_jobs_by_user(
    user_id: int, limit: int = 20, offset: int = 0, q: str = "",
    date_from: str = "", date_to: str = "",
    extra_tools: list[str] | None = None,
    tool_filter: list[str] | None = None,
) -> tuple[list[dict], int]:
    conditions = ["user_id = %s", "(expires_at IS NULL OR expires_at > NOW())"]
    params: list = [user_id]
    if q:
        like = f"%{q}%"
        if extra_tools:
            conditions.append("(original_filename ILIKE %s OR tool ILIKE %s OR tool = ANY(%s))")
            params += [like, like, extra_tools]
        else:
            conditions.append("(original_filename ILIKE %s OR tool ILIKE %s)")
            params += [like, like]
    if tool_filter:
        conditions.append("tool = ANY(%s)")
        params.append(tool_filter)
    if date_from:
        conditions.append("created_at::date >= %s::date")
        params.append(date_from)
    if date_to:
        conditions.append("created_at::date <= %s::date")
        params.append(date_to)
    where = " AND ".join(conditions)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(f"SELECT COUNT(*) AS total FROM jobs WHERE {where}", params)
            total = cur.fetchone()["total"]
            cur.execute(
                f"SELECT * FROM jobs WHERE {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                params + [limit, offset],
            )
            rows = cur.fetchall()
    return [dict(row) for row in rows], total


def count_active_jobs_for_tool(user_id: int, tools: list[str]) -> int:
    """Jobs of the given tools that occupy a worker or are about to.

    A job waiting for the person (``awaiting_user``, ``paused``) lies still and is not
    counted, the same rule ``count_working_jobs`` applies across all tools.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) FROM jobs
                   WHERE user_id = %s AND tool = ANY(%s)
                   AND status IN ('pending', 'running', 'queued', 'waiting_retry')""",
                (user_id, tools),
            )
            row = cur.fetchone()
            return row[0] if row else 0


def has_active_job_for_tool(user_id: int, tools: list[str]) -> bool:
    """Return True if the user has a job of the given tools that is actually working."""
    return count_active_jobs_for_tool(user_id, tools) > 0


def count_working_jobs(user_id: int, voice: bool | None = None) -> int:
    """Jobs that occupy a worker or are about to, only those with or without a voice when asked.

    A job waiting for the person (``awaiting_user``, ``paused``) lies still and is not counted,
    one that resumes by itself (``waiting_retry``) is.
    """
    sql = """SELECT COUNT(*) FROM jobs
               WHERE user_id = %s AND status IN ('pending', 'running', 'queued', 'waiting_retry')"""
    params: list = [user_id]
    if voice is not None:
        sql += " AND (tool = ANY(%s)) = %s"
        params += [sorted(VOICE_TOOLS), voice]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else 0


def count_all_jobs_for_tool(user_id: int, tools: list[str]) -> int:
    """Return total non-terminal jobs (pending/running/awaiting_user/queued) for quota/queue-size checks."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) FROM jobs
                   WHERE user_id = %s AND tool = ANY(%s)
                   AND status IN ('pending', 'running', 'awaiting_user', 'queued')""",
                (user_id, tools),
            )
            row = cur.fetchone()
            return row[0] if row else 0


def get_next_queued_job(user_id: int, tools: list[str]) -> dict | None:
    """Fetches the oldest waiting job, but only when the user has none running."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """UPDATE jobs SET status = 'pending'
                   WHERE job_uuid = (
                       SELECT j.job_uuid FROM jobs j
                       WHERE j.user_id = %s AND j.tool = ANY(%s) AND j.status = 'queued'
                       AND NOT EXISTS (
                           SELECT 1 FROM jobs a
                           WHERE a.user_id = %s AND a.tool = ANY(%s)
                           AND a.status IN ('pending', 'running')
                       )
                       ORDER BY j.created_at ASC
                       LIMIT 1
                       FOR UPDATE SKIP LOCKED
                   )
                   RETURNING *""",
                (user_id, tools, user_id, tools),
            )
            conn.commit()
            row = cur.fetchone()
            result = dict(row) if row else None
    if result:
        _notify_job_update(result["job_uuid"])
    return result


def count_all_jobs_for_tool_excluding(user_id: int, tools: list[str], exclude_uuid: str) -> int:
    """Count active/queued jobs (pending/running/awaiting_user/queued) excluding a specific job."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) FROM jobs
                   WHERE user_id = %s AND tool = ANY(%s)
                   AND status IN ('pending', 'running', 'awaiting_user', 'queued')
                   AND job_uuid != %s""",
                (user_id, tools, exclude_uuid),
            )
            row = cur.fetchone()
            return row[0] if row else 0


def get_all_results_for_user(user_id: int) -> list[dict]:
    """Return all jobs with a result_path for the given user, ordered oldest first."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """SELECT id, job_uuid, result_path, result_filename, original_filename FROM jobs
                   WHERE user_id = %s AND result_path IS NOT NULL AND status != 'failed'
                   ORDER BY created_at ASC""",
                (user_id,),
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]


def get_all_jobs(
    limit: int = 50, offset: int = 0, q: str = "",
    date_from: str = "", date_to: str = "",
    extra_tools: list[str] | None = None,
) -> tuple[list[dict], int]:
    """All jobs of all users with the display name, newest first."""
    conditions = ["(j.expires_at IS NULL OR j.expires_at > NOW())"]
    params: list = []

    if q:
        like = f"%{q}%"
        if extra_tools:
            conditions.append(
                "(u.display_name ILIKE %s OR u.username ILIKE %s OR j.tool ILIKE %s OR j.original_filename ILIKE %s OR j.tool = ANY(%s))"
            )
            params += [like, like, like, like, extra_tools]
        else:
            conditions.append(
                "(u.display_name ILIKE %s OR u.username ILIKE %s OR j.tool ILIKE %s OR j.original_filename ILIKE %s)"
            )
            params += [like, like, like, like]
    if date_from:
        conditions.append("j.created_at >= %s::timestamp")
        params.append(_de_date_to_utc(date_from))
    if date_to:
        conditions.append("j.created_at <= %s::timestamp")
        params.append(_de_date_to_utc(date_to, end_of_day=True))

    where = "WHERE " + " AND ".join(conditions)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                f"""SELECT j.*, u.display_name AS user_display_name, u.username
                   FROM jobs j
                   JOIN users u ON j.user_id = u.id
                   {where}
                   ORDER BY j.created_at DESC
                   LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            rows = cur.fetchall()
            cur.execute(
                f"""SELECT COUNT(*) AS total FROM jobs j
                   JOIN users u ON j.user_id = u.id
                   {where}""",
                params,
            )
            total = cur.fetchone()["total"]
    return [dict(row) for row in rows], total
