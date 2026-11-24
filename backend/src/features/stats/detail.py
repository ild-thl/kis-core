"""Everything about one person or one module in one place."""
from psycopg2.extras import RealDictCursor

from src.core.db.pool import get_connection
from src.features.stats.assistant import FACHSPRACHE, KACHEL, SPRACHE

# How many of the most recent jobs the detail view shows.
LETZTE_JOBS = 5

# How many merged events one page of the Verlauf shows.
VERLAUF_SEITE = 50

# How many recent online-sessions the Verlauf shows.
SITZUNGEN_ANZAHL = 20

# Chat preview: supervision needs the wording, not just "message sent".
VORSCHAU_LAENGE = 140


def user_detail(user_id: int) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT u.id, COALESCE(u.display_name, u.username, 'Unbekannt') AS name,
                          COALESCE(c.name, u.role) AS rolle, u.language_level AS niveau,
                          u.created_at
                   FROM users u LEFT JOIN custom_roles c ON u.custom_role_id = c.id
                   WHERE u.id = %s""",
                (user_id,),
            )
            kopf = cur.fetchone()
            if not kopf:
                return None

            cur.execute(
                "SELECT MAX(day) AS zuletzt, COUNT(DISTINCT day) AS tage FROM user_presence WHERE user_id = %s",
                (user_id,),
            )
            anwesend = cur.fetchone()

            cur.execute(
                """SELECT tool, COUNT(*) AS n FROM jobs WHERE user_id = %s
                   GROUP BY tool ORDER BY 2 DESC""",
                (user_id,),
            )
            werkzeuge = [{"tool": r["tool"], "jobs": r["n"]} for r in cur.fetchall()]

            cur.execute(
                """SELECT tool, status, created_at FROM jobs WHERE user_id = %s
                   ORDER BY created_at DESC LIMIT %s""",
                (user_id, LETZTE_JOBS),
            )
            letzte = [
                {"tool": r["tool"], "status": r["status"],
                 "when": r["created_at"].isoformat() + "Z" if r["created_at"] else None}
                for r in cur.fetchall()
            ]

            cur.execute(
                """SELECT m.title, m.uuid,
                          CASE WHEN m.user_id = %s THEN 'owner' ELSE 'member' END AS rolle,
                          (SELECT COUNT(*) FROM aia_exercise_progress p
                             JOIN aia_exercise_sets s ON s.id = p.set_id
                            WHERE s.workspace_id = m.id AND p.user_id = %s) AS uebungen,
                          (SELECT COUNT(*) FROM aia_messages msg
                            WHERE msg.workspace_id = m.id AND msg.user_id = %s
                              AND msg.role = 'user') AS chat
                   FROM aia_workspaces m
                   WHERE (m.user_id = %s
                      OR EXISTS (SELECT 1 FROM aia_enrollments e
                                  WHERE e.workspace_id = m.id AND e.user_id = %s))
                   ORDER BY 4 DESC""",
                (user_id, user_id, user_id, user_id, user_id),
            )
            module = [
                {"title": r["title"], "uuid": r["uuid"], "role": r["rolle"],
                 "answered": r["uebungen"], "chat": r["chat"]}
                for r in cur.fetchall()
            ]

            return {
                "id": kopf["id"],
                "name": kopf["name"],
                "role": kopf["rolle"],
                "level": kopf["niveau"],
                "since": kopf["created_at"].strftime("%m/%Y") if kopf["created_at"] else None,
                "last_seen": str(anwesend["zuletzt"]) if anwesend["zuletzt"] else None,
                "present_days": anwesend["tage"],
                "totals": {
                    "jobs": sum(w["jobs"] for w in werkzeuge),
                    "answered": sum(m["answered"] for m in module),
                    "chat": sum(m["chat"] for m in module),
                },
                "tools": werkzeuge,
                "modules": module,
                "recent": letzte,
            }


def workspace_detail(uuid: str) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT m.id, m.uuid, m.title, m.is_active, m.created_at,
                          m.user_id AS owner_id,
                          COALESCE(u.display_name, u.username, 'Unbekannt') AS owner
                   FROM aia_workspaces m JOIN users u ON m.user_id = u.id
                   WHERE m.uuid = %s""",
                (uuid,),
            )
            kopf = cur.fetchone()
            if not kopf:
                return None
            mid = kopf["id"]

            material = _workspace_materials(cur, mid)
            sortiert = _workspace_tools(cur, mid)
            leute = _workspace_members(cur, mid, kopf["owner_id"])

            cur.execute(
                """SELECT COUNT(*) AS n, MAX(created_at) AS zuletzt
                   FROM aia_messages WHERE workspace_id = %s AND role = 'user'""",
                (mid,),
            )
            chat = cur.fetchone()

            return {
                "uuid": kopf["uuid"],
                "title": kopf["title"],
                "owner": kopf["owner"],
                "active": kopf["is_active"],
                "since": kopf["created_at"].strftime("%m/%Y") if kopf["created_at"] else None,
                "last": chat["zuletzt"].isoformat() + "Z" if chat["zuletzt"] else None,
                "totals": {
                    "members": len(leute),
                    "sources": len(material),
                    "created": sum(x["created"] for g in sortiert.values() for x in g),
                    "answered": sum(x["answered"] for g in sortiert.values() for x in g),
                    "chat": chat["n"],
                },
                "source_tools": sortiert["source"],
                "glossary_tools": sortiert["glossary"],
                "materials": material,
                "members": leute,
            }


def _workspace_materials(cur, mid: int) -> list[dict]:
    cur.execute(
        """SELECT filename, file_type, chunk_count, status
           FROM aia_sources WHERE workspace_id = %s
           ORDER BY chunk_count DESC""",
        (mid,),
    )
    return [
        {"name": r["filename"], "kind": r["file_type"],
         "chunks": r["chunk_count"], "status": r["status"]}
        for r in cur.fetchall()
    ]


def _workspace_tools(cur, mid: int) -> dict[str, list[dict]]:
    """Created and answered items per tool, the two trainers kept apart as in the module itself."""
    cur.execute(
        """SELECT s.tool,
                  (SELECT COUNT(*) FROM aia_exercise_items i WHERE i.set_id = s.id) AS erzeugt,
                  (SELECT COUNT(*) FROM aia_exercise_progress p WHERE p.set_id = s.id) AS beantwortet
           FROM aia_exercise_sets s WHERE s.workspace_id = %s""",
        (mid,),
    )
    gruppen: dict[str, dict[str, dict]] = {"source": {}, "glossary": {}}
    for r in cur.fetchall():
        # The group hangs off the tool, not off the mode.
        kachel = KACHEL.get(r["tool"])
        if kachel in FACHSPRACHE:
            wohin = "source"
        elif kachel in SPRACHE:
            wohin = "glossary"
        else:
            continue
        eintrag = gruppen[wohin].setdefault(
            kachel, {"tool": kachel, "created": 0, "answered": 0}
        )
        eintrag["created"] += int(r["erzeugt"])
        eintrag["answered"] += int(r["beantwortet"])

    return {
        k: sorted(v.values(), key=lambda x: x["created"], reverse=True)
        for k, v in gruppen.items()
    }


def _workspace_members(cur, mid: int, owner_id: int) -> list[dict]:
    """Owner and enrolled people with their numbers, tools and last activity in this module."""
    # The owner was missing entirely, enrollments are grouped per person.
    cur.execute(
        """SELECT u.id AS user_id,
                  COALESCE(u.display_name, u.username, 'Unbekannt') AS name,
                  t.rolle,
                  (SELECT COUNT(*) FROM aia_exercise_progress p
                     JOIN aia_exercise_sets s ON s.id = p.set_id
                    WHERE s.workspace_id = %s AND p.user_id = u.id) AS uebungen,
                  (SELECT COUNT(*) FROM aia_messages msg
                    WHERE msg.workspace_id = %s AND msg.user_id = u.id
                      AND msg.role = 'user') AS chat
           FROM (
               SELECT %s::int AS user_id, 'owner' AS rolle
               UNION ALL
               SELECT e.user_id,
                      CASE WHEN BOOL_OR(e.role = 'tutor')
                           THEN 'tutor' ELSE 'student' END
               FROM aia_enrollments e
               WHERE e.workspace_id = %s AND e.user_id <> %s
               GROUP BY e.user_id
           ) t
           JOIN users u ON u.id = t.user_id
           ORDER BY CASE t.rolle WHEN 'owner' THEN 0
                                 WHEN 'tutor' THEN 1 ELSE 2 END, 3 DESC""",
        (mid, mid, owner_id, mid, owner_id),
    )
    personen = cur.fetchall()

    # Tools and last activity stay separate queries, both grouped per person.
    cur.execute(
        """SELECT p.user_id, s.tool, COUNT(*) AS n
           FROM aia_exercise_progress p
           JOIN aia_exercise_sets s ON s.id = p.set_id
           WHERE s.workspace_id = %s
           GROUP BY p.user_id, s.tool""",
        (mid,),
    )
    werkzeuge_je_person: dict[int, list[dict]] = {}
    for r in cur.fetchall():
        kachel = KACHEL.get(r["tool"])
        if kachel is None:
            continue
        werkzeuge_je_person.setdefault(r["user_id"], []).append(
            {"tool": kachel, "answered": r["n"]}
        )
    for zeilen in werkzeuge_je_person.values():
        zeilen.sort(key=lambda x: x["answered"], reverse=True)

    # Presence is platform-wide, here only activity in this module counts.
    cur.execute(
        """SELECT user_id, MAX(wann) AS zuletzt FROM (
               SELECT user_id, created_at AS wann FROM aia_messages
                WHERE workspace_id = %s AND role = 'user'
               UNION ALL
               SELECT p.user_id, p.answered_at AS wann
                 FROM aia_exercise_progress p
                 JOIN aia_exercise_sets s ON s.id = p.set_id
                WHERE s.workspace_id = %s
           ) x GROUP BY user_id""",
        (mid, mid),
    )
    letzte_je_person = {r["user_id"]: r["zuletzt"] for r in cur.fetchall()}

    leute = []
    for r in personen:
        zuletzt = letzte_je_person.get(r["user_id"])
        leute.append({
            "name": r["name"], "role": r["rolle"],
            "answered": r["uebungen"], "chat": r["chat"],
            "last": zuletzt.isoformat() + "Z" if zuletzt else None,
            "tools": werkzeuge_je_person.get(r["user_id"], []),
        })
    return leute


def user_verlauf(user_id: int, vor: str | None = None) -> dict:
    """Chat, tools, exercises and joins mixed, newest first, sessions separately."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            grenze = "AND wann < %(vor)s" if vor else ""
            cur.execute(
                f"""SELECT * FROM (
                        SELECT 'chat' AS art, m.title AS modul, msg.content AS text,
                               NULL AS werkzeug, NULL AS status, msg.created_at AS wann
                          FROM aia_messages msg JOIN aia_workspaces m ON m.id = msg.workspace_id
                         WHERE msg.user_id = %(uid)s AND msg.role = 'user'
                        UNION ALL
                        SELECT 'werkzeug', NULL, j.original_filename,
                               j.tool, j.status, j.created_at
                          FROM jobs j WHERE j.user_id = %(uid)s
                        UNION ALL
                        SELECT 'uebung', m.title, NULL, s.tool, NULL, p.answered_at
                          FROM aia_exercise_progress p
                          JOIN aia_exercise_sets s ON s.id = p.set_id
                          JOIN aia_workspaces m ON m.id = s.workspace_id
                         WHERE p.user_id = %(uid)s
                        UNION ALL
                        SELECT 'beitritt', m.title, NULL, NULL, e.role, e.created_at
                          FROM aia_enrollments e JOIN aia_workspaces m ON m.id = e.workspace_id
                         WHERE e.user_id = %(uid)s
                    ) x
                    WHERE wann IS NOT NULL {grenze}
                    ORDER BY wann DESC LIMIT {VERLAUF_SEITE}""",
                {"uid": user_id, "vor": vor},
            )
            eintraege = [
                {
                    "kind": r["art"], "module": r["modul"], "text": _vorschau(r["text"]),
                    "tool": r["werkzeug"], "status": r["status"],
                    "when": r["wann"].isoformat() + "Z",
                }
                for r in cur.fetchall()
            ]

            # 500 hours suffice to build the last sessions without loading the whole history.
            cur.execute(
                """SELECT day, hour FROM user_presence
                    WHERE user_id = %s ORDER BY day DESC, hour DESC LIMIT 500""",
                (user_id,),
            )
            sitzungen = _sitzungen(cur.fetchall())[:SITZUNGEN_ANZAHL]

            return {
                "events": eintraege,
                "has_more": len(eintraege) == VERLAUF_SEITE,
                "sessions": sitzungen,
            }


def _vorschau(text: str | None) -> str | None:
    if text is None or len(text) <= VORSCHAU_LAENGE:
        return text
    return text[:VORSCHAU_LAENGE].rstrip() + "…"


def _sitzungen(zeilen: list[dict]) -> list[dict]:
    """Merges consecutive hours per day into one session."""
    nach_tag: dict[str, list[int]] = {}
    for r in zeilen:
        nach_tag.setdefault(str(r["day"]), []).append(r["hour"])

    bloecke = []
    for tag, stunden in nach_tag.items():
        stunden = sorted(set(stunden))
        start = vorherige = stunden[0]
        for h in stunden[1:] + [None]:
            if h is None or h != vorherige + 1:
                bloecke.append({"day": tag, "from": start, "to": vorherige})
                start = h
            vorherige = h

    bloecke.sort(key=lambda b: (b["day"], b["from"]), reverse=True)
    return bloecke
