"""Zahlen zum KI-Assistenten: Module, Materialien, Werkzeuge, Sprachniveau."""
from psycopg2.extras import RealDictCursor

from src.core.db.pool import get_connection

# The two tile groups from the module, named like the tiles there.
FACHSPRACHE = ["karteikarten", "quiz", "dataTable", "mindmap"]
SPRACHE = ["lernkarten", "vocabulary", "grammar"]

# Maps the name in the database onto the name of the tile.
KACHEL = {
    "karteikarten": "karteikarten",
    "quiz": "quiz",
    "flashcards": "lernkarten",
    "wortschatz": "vocabulary",
    "grammatik": "grammar",
}


def assistant_overview() -> dict:
    """Everything the AI assistant tab needs."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            return {
                "totals": _totals(cur),
                "levels": _levels(cur),
                "materials": _materials(cur),
                "tools": _tools(cur),
                "heat": _heat(cur),
                "workspaces": _workspaces(cur),
            }


def _totals(cur) -> dict:
    cur.execute("SELECT COUNT(*) AS n FROM aia_workspaces")
    module = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) AS n FROM aia_exercise_progress")
    beantwortet = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) AS n FROM aia_messages WHERE role = 'user'")
    chat = cur.fetchone()["n"]
    return {"workspaces": module, "answered": beantwortet, "chat": chat}


def _levels(cur) -> list[dict]:
    """Language level of the participants, comes ready from the assessment."""
    cur.execute(
        """SELECT language_level AS stufe, COUNT(*) AS n
           FROM users WHERE language_level IS NOT NULL
           GROUP BY 1"""
    )
    gefunden = {r["stufe"]: r["n"] for r in cur.fetchall()}
    return [{"level": s, "users": gefunden.get(s, 0)} for s in ("A1", "A2", "B1", "B2", "C1", "C2")]


def _materials(cur) -> dict:
    """Grouped by kind, office files count as PDF."""
    cur.execute(
        """SELECT CASE
                    WHEN file_type = 'pdf' THEN 'PDF'
                    WHEN file_type IN ('mp4', 'webm') THEN 'Video'
                    ELSE 'Audio'
                  END AS art,
                  COUNT(*) AS anzahl,
                  COALESCE(SUM(chunk_count), 0) AS abschnitte
           FROM aia_sources GROUP BY 1 ORDER BY 2 DESC"""
    )
    zeilen = [
        {"kind": r["art"], "count": r["anzahl"], "chunks": int(r["abschnitte"])}
        for r in cur.fetchall()
    ]
    return {
        "rows": zeilen,
        "total": {
            "count": sum(z["count"] for z in zeilen),
            "chunks": sum(z["chunks"] for z in zeilen),
        },
    }


def _tools(cur) -> dict:
    """The seven tools in their two groups, one set is one use."""
    cur.execute("SELECT tool, COUNT(*) AS n FROM aia_exercise_sets GROUP BY tool")
    je_tool = {KACHEL[r["tool"]]: int(r["n"]) for r in cur.fetchall() if r["tool"] in KACHEL}
    cur.execute("SELECT COUNT(*) AS n FROM aia_mindmaps")
    je_tool["mindmap"] = int(cur.fetchone()["n"])
    cur.execute("SELECT COUNT(*) AS n FROM aia_data_tables")
    je_tool["dataTable"] = int(cur.fetchone()["n"])

    def gruppe(schluessel: list[str]) -> list[dict]:
        zeilen = [{"tool": k, "count": je_tool.get(k, 0)} for k in schluessel]
        return sorted(zeilen, key=lambda z: z["count"], reverse=True)

    return {"source": gruppe(FACHSPRACHE), "glossary": gruppe(SPRACHE)}


def _heat(cur) -> list[list[float]]:
    """When requests go to the AI, per weekday and hour."""
    cur.execute(
        """SELECT EXTRACT(ISODOW FROM (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Berlin'))::int AS wochentag,
                  EXTRACT(HOUR   FROM (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Berlin'))::int AS stunde,
                  COUNT(*)::float AS summe,
                  COUNT(DISTINCT (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Berlin')::date)::float AS tage
           FROM aia_messages WHERE role = 'user'
           GROUP BY 1, 2"""
    )
    raster = [[0.0] * 24 for _ in range(7)]
    for r in cur.fetchall():
        raster[r["wochentag"] - 1][r["stunde"]] = r["summe"] / max(1.0, r["tage"])
    return raster


def _workspaces(cur) -> list[dict]:
    """The modules with their numbers, in one query instead of one per module."""
    cur.execute(
        """SELECT m.uuid, m.title, m.is_active, m.created_at,
                  COALESCE(u.display_name, u.username, 'Unbekannt') AS owner,
                  (SELECT COUNT(*) FROM aia_sources s WHERE s.workspace_id = m.id) AS quellen,
                  -- Der Eigentuemer steht in keiner Einschreibung. Ohne das
                  -- "+ 1" stuende in der Zeile eine andere Zahl als im Fenster,
                  -- das dieselbe Zeile oeffnet.
                  (SELECT COUNT(DISTINCT e.user_id) FROM aia_enrollments e
                    WHERE e.workspace_id = m.id AND e.user_id <> m.user_id) + 1 AS teilnehmer,
                  (SELECT COUNT(*) FROM aia_exercise_items i
                     JOIN aia_exercise_sets es ON es.id = i.set_id
                    WHERE es.workspace_id = m.id) AS erzeugt,
                  (SELECT COUNT(*) FROM aia_exercise_progress p
                     JOIN aia_exercise_sets es2 ON es2.id = p.set_id
                    WHERE es2.workspace_id = m.id) AS beantwortet,
                  (SELECT COUNT(*) FROM aia_messages msg
                    WHERE msg.workspace_id = m.id AND msg.role = 'user') AS chat,
                  (SELECT MAX(msg2.created_at) FROM aia_messages msg2
                    WHERE msg2.workspace_id = m.id) AS zuletzt
           FROM aia_workspaces m
           JOIN users u ON m.user_id = u.id
           ORDER BY 10 DESC NULLS LAST, m.created_at DESC"""
    )
    return [
        {
            "uuid": r["uuid"],
            "title": r["title"],
            "owner": r["owner"],
            "active": r["is_active"],
            "sources": r["quellen"],
            "members": r["teilnehmer"],
            "created": r["erzeugt"],
            "answered": r["beantwortet"],
            "chat": r["chat"],
            "last": r["zuletzt"].isoformat() + "Z" if r["zuletzt"] else None,
        }
        for r in cur.fetchall()
    ]
