"""User numbers, based on presence instead of on jobs."""
import time
from datetime import datetime

from psycopg2.extras import RealDictCursor

from src.core.db.pool import get_connection
from src.security import presence
from src.utils.local_date import LOCAL_TZ

# From how many days with presence someone counts as regular.
REGELMAESSIG_AB_TAGEN = 10


def user_overview() -> dict:
    """Everything the users tab needs, in one go."""
    seit = presence.online_since()
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            return {
                "online": _online_details(cur, seit),
                "totals": _totals(cur),
                "per_day": _per_day(cur),
                "today_by_hour": _today_by_hour(cur),
                "new_per_month": _new_per_month(cur),
                "retention": _retention(cur),
                "roles": _roles(cur),
                "people": _people(cur),
            }


def _online_details(cur, seit: dict[int, int]) -> dict:
    """Names for the ids, only those that can be resolved are counted."""
    if not seit:
        return {"count": 0, "users": []}
    jetzt = int(time.time())
    cur.execute(
        """SELECT id, display_name, username
           FROM users WHERE id = ANY(%s) ORDER BY display_name""",
        (list(seit),),
    )
    users = [
        {
            "id": r["id"],
            "name": r["display_name"] or r["username"] or "Unbekannt",
            # Minutes since the first sign of life, not since the last.
            "minutes": max(0, (jetzt - seit[r["id"]]) // 60),
        }
        for r in cur.fetchall()
    ]
    users.sort(key=lambda u: -u["minutes"])
    return {"count": len(users), "users": users}


def _totals(cur) -> dict:
    cur.execute("SELECT COUNT(*) AS n FROM users")
    gesamt = cur.fetchone()["n"]
    cur.execute(
        """SELECT COUNT(DISTINCT user_id) AS n FROM user_presence
           WHERE day >= CURRENT_DATE - 30"""
    )
    aktiv = cur.fetchone()["n"]
    cur.execute(
        """SELECT COUNT(*) AS n FROM users
           WHERE date_trunc('month', created_at) = date_trunc('month', CURRENT_DATE)"""
    )
    neu = cur.fetchone()["n"]
    return {"total": gesamt, "active_30d": aktiv, "new_this_month": neu}


def _per_day(cur) -> list[dict]:
    """Verschiedene Personen je Tag, letzte 30 Tage."""
    cur.execute(
        """SELECT day, COUNT(DISTINCT user_id) AS n
           FROM user_presence WHERE day >= CURRENT_DATE - 30
           GROUP BY day ORDER BY day"""
    )
    return [{"day": str(r["day"]), "users": r["n"]} for r in cur.fetchall()]


def _today_by_hour(cur) -> list[dict]:
    """Today hour by hour, the current hour stays out."""
    aktuelle_stunde = datetime.now(LOCAL_TZ).hour
    cur.execute(
        """SELECT hour, COUNT(DISTINCT user_id) AS n
           FROM user_presence
           WHERE day = (NOW() AT TIME ZONE 'Europe/Berlin')::date
             AND hour < %s
           GROUP BY hour ORDER BY hour""",
        (aktuelle_stunde,),
    )
    gefunden = {int(r["hour"]): r["n"] for r in cur.fetchall()}
    return [{"hour": h, "users": gefunden.get(h, 0)} for h in range(aktuelle_stunde)]


def users_by_hour(hour: int) -> list[dict]:
    """Who was counted in this hour today, mirrors _today_by_hour's bucket."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            return _users_by_hour(cur, hour)


def _users_by_hour(cur, hour: int) -> list[dict]:
    """LEFT JOIN, a deleted user's presence row stays and must still count."""
    cur.execute(
        """SELECT p.user_id AS id, COALESCE(u.display_name, u.username, 'Unbekannt') AS name
           FROM user_presence p LEFT JOIN users u ON u.id = p.user_id
           WHERE p.day = (NOW() AT TIME ZONE 'Europe/Berlin')::date AND p.hour = %s
           ORDER BY 2""",
        (hour,),
    )
    return [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]


def users_by_day(day: str) -> list[dict]:
    """Who was counted on this day, mirrors _per_day's bucket."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            return _users_by_day(cur, day)


def _users_by_day(cur, day: str) -> list[dict]:
    """DISTINCT because one user shows up once per hour, LEFT JOIN keeps deleted users' rows."""
    cur.execute(
        """SELECT DISTINCT p.user_id AS id, COALESCE(u.display_name, u.username, 'Unbekannt') AS name
           FROM user_presence p LEFT JOIN users u ON u.id = p.user_id
           WHERE p.day = %s
           ORDER BY 2""",
        (day,),
    )
    return [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]


def users_new_in_month(month: str) -> list[dict]:
    """Who registered in this month, month as 'MM/YY' like the chart already shows it."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            return _users_new_in_month(cur, month)


def _users_new_in_month(cur, month: str) -> list[dict]:
    cur.execute(
        """SELECT id, COALESCE(display_name, username, 'Unbekannt') AS name
           FROM users WHERE date_trunc('month', created_at) = to_date(%s, 'MM/YY')
           ORDER BY 2""",
        (month,),
    )
    return [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]


def _new_per_month(cur) -> list[dict]:
    cur.execute(
        """SELECT to_char(date_trunc('month', created_at), 'MM/YY') AS monat,
                  date_trunc('month', created_at) AS sortier,
                  COUNT(*) AS n
           FROM users GROUP BY 1, 2 ORDER BY 2"""
    )
    return [{"month": r["monat"], "users": r["n"]} for r in cur.fetchall()]


def _retention(cur) -> dict:
    """How many days someone was here, in three groups."""
    cur.execute(
        """SELECT tage, COUNT(*) AS n FROM (
               SELECT user_id, COUNT(DISTINCT day) AS tage
               FROM user_presence GROUP BY user_id
           ) je_nutzer
           GROUP BY tage"""
    )
    regelmaessig = gelegentlich = einmal = 0
    for r in cur.fetchall():
        if r["tage"] > REGELMAESSIG_AB_TAGEN:
            regelmaessig += r["n"]
        elif r["tage"] > 1:
            gelegentlich += r["n"]
        else:
            einmal += r["n"]
    return {
        "regular": regelmaessig,
        "occasional": gelegentlich,
        "once": einmal,
        "threshold_days": REGELMAESSIG_AB_TAGEN,
    }


def _people(cur) -> list[dict]:
    """All names for the search, the detail view fetches the rest."""
    cur.execute(
        """SELECT u.id, COALESCE(u.display_name, u.username, 'Unbekannt') AS name,
                  COALESCE(c.name, u.role) AS rolle
           FROM users u LEFT JOIN custom_roles c ON u.custom_role_id = c.id
           ORDER BY 2"""
    )
    return [{"id": r["id"], "name": r["name"], "role": r["rolle"]} for r in cur.fetchall()]


def _roles(cur) -> list[dict]:
    cur.execute(
        """SELECT COALESCE(c.name, u.role) AS rolle, COUNT(*) AS n
           FROM users u
           LEFT JOIN custom_roles c ON u.custom_role_id = c.id
           GROUP BY 1 ORDER BY 2 DESC"""
    )
    return [{"role": r["rolle"], "users": r["n"]} for r in cur.fetchall()]
