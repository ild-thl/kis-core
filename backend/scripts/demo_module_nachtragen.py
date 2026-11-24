"""Once: every active account gets every active demo module, plus the mark that says so.

Needed because the mark used to be one per account, so a demo module added later
never reached anybody who had logged in before. Owners of a demo module are left
alone, and an existing enrollment is kept as it is.

Dry run:  docker exec kis-backend python scripts/demo_module_nachtragen.py
Really:   docker exec kis-backend python scripts/demo_module_nachtragen.py --schreiben
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import database  # noqa: E402

_PAARE = """
    SELECT m.id AS workspace_id, m.title, u.id AS user_id, u.username,
           (e.id IS NOT NULL) AS drin,
           (ds.user_id IS NOT NULL) AS gemerkt
      FROM aia_workspaces m
      JOIN users besitzer ON besitzer.id = m.user_id AND besitzer.is_demo
     CROSS JOIN users u
      LEFT JOIN aia_enrollments e ON e.workspace_id = m.id AND e.user_id = u.id
      LEFT JOIN aia_demo_seeded ds ON ds.workspace_id = m.id AND ds.user_id = u.id
     WHERE m.is_active AND u.active = 1 AND u.id <> m.user_id
     ORDER BY m.id, u.id
"""


def main() -> int:
    schreiben = "--schreiben" in sys.argv
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_PAARE)
            paare = cur.fetchall()

            fehlt_einschreibung = [p for p in paare if not p[4]]
            fehlt_marke = [p for p in paare if not p[5]]
            for workspace_id, titel, user_id, name, *_ in fehlt_einschreibung:
                print(f"  + {name} -> {titel}")

            if schreiben:
                for workspace_id, _titel, user_id, *_ in fehlt_einschreibung:
                    cur.execute(
                        """INSERT INTO aia_enrollments (workspace_id, user_id, role, via_demo)
                           VALUES (%s, %s, 'student', TRUE)
                           ON CONFLICT (workspace_id, user_id) DO NOTHING""",
                        (workspace_id, user_id),
                    )
                for workspace_id, _titel, user_id, *_ in fehlt_marke:
                    cur.execute(
                        """INSERT INTO aia_demo_seeded (workspace_id, user_id)
                           VALUES (%s, %s)
                           ON CONFLICT (workspace_id, user_id) DO NOTHING""",
                        (workspace_id, user_id),
                    )
                conn.commit()

    print(f"Paare gesamt: {len(paare)}")
    print(f"Fehlende Einschreibungen: {len(fehlt_einschreibung)}")
    print(f"Fehlende Marken: {len(fehlt_marke)}")
    print("Geschrieben." if schreiben else "Nur Vorschau, nichts geschrieben (--schreiben zum Ausfuehren).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
