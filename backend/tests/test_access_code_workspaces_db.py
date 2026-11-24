"""An access code enrolls its accounts into the chosen workspaces, checked on the real schema."""

import os
import uuid as uuid_modul
from datetime import datetime, timedelta

import pytest

psycopg2 = pytest.importorskip("psycopg2")

from src.features.access_codes import repository as repo  # noqa: E402


@pytest.fixture(scope="module")
def verbindung():
    """A database connection or a clean skip."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("kein DATABASE_URL gesetzt (Test braucht echtes Postgres)")
    from src.core.db.pool import get_connection
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception as fehler:  # pragma: no cover - nur ausserhalb des Stacks
        pytest.skip(f"Datenbank nicht erreichbar: {fehler}")
    return get_connection


@pytest.fixture
def aufbau(verbindung):
    """An owner with two workspaces, a code and two accounts from it, all removed afterwards."""
    from src.core.db.schema import init_db
    init_db()
    kennung = uuid_modul.uuid4().hex[:8]
    code_id = repo.create_code(
        code=f"ASKF-WS-{kennung.upper()}", label="Testrunde Workspaces", role="user",
        custom_role_id=None, max_uses=5, valid_until=datetime.now() + timedelta(days=30),
        access_hours=None, show_credentials=True, show_evaluation=False, created_by=0,
    )
    with verbindung() as conn:
        with conn.cursor() as cur:
            konten = []
            for name in ("besitzer", "eins", "zwei"):
                cur.execute(
                    "INSERT INTO users (username, display_name, email, active, role) "
                    "VALUES (%s, %s, %s, 1, 'staff') RETURNING id",
                    (f"test.ws.{name}.{kennung}", f"Test {name}", f"test.ws.{name}.{kennung}@demo.askfrancis.local"),
                )
                konten.append(cur.fetchone()[0])
            besitzer, eins, zwei = konten
            arbeitsbereiche = []
            for titel in ("Recht", "Physik"):
                cur.execute(
                    "INSERT INTO aia_workspaces (uuid, user_id, title) VALUES (%s, %s, %s) RETURNING id",
                    (str(uuid_modul.uuid4()), besitzer, f"{titel} {kennung}"),
                )
                arbeitsbereiche.append(cur.fetchone()[0])
        conn.commit()
    for konto in (eins, zwei):
        repo.set_user_access(konto, expires_at=None, code_id=code_id)
    yield {"code_id": code_id, "besitzer": besitzer, "konten": [eins, zwei], "ws": arbeitsbereiche}
    with verbindung() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM aia_workspaces WHERE id = ANY(%s)", (arbeitsbereiche,))
            cur.execute("DELETE FROM users WHERE id = ANY(%s)", (konten,))
            cur.execute("DELETE FROM access_codes WHERE id = %s", (code_id,))
        conn.commit()


def _einschreibungen(verbindung, konten):
    with verbindung() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT workspace_id, user_id, role FROM aia_enrollments WHERE user_id = ANY(%s)",
                (konten,),
            )
            return set(cur.fetchall())


def test_accounts_land_in_every_chosen_workspace_as_learners(verbindung, aufbau):
    recht, physik = aufbau["ws"]
    eins, zwei = aufbau["konten"]
    repo.set_code_workspaces(aufbau["code_id"], [recht, physik])

    assert repo.enroll_into_code_workspaces(aufbau["code_id"], [eins, zwei]) == 4
    assert _einschreibungen(verbindung, [eins, zwei]) == {
        (recht, eins, "student"), (physik, eins, "student"),
        (recht, zwei, "student"), (physik, zwei, "student"),
    }
    # A second run changes nothing.
    assert repo.enroll_into_code_workspaces(aufbau["code_id"], [eins, zwei]) == 0


def test_the_owner_is_never_enrolled_into_their_own_workspace(verbindung, aufbau):
    repo.set_code_workspaces(aufbau["code_id"], aufbau["ws"])

    assert repo.enroll_into_code_workspaces(aufbau["code_id"], [aufbau["besitzer"]]) == 0


def test_replacing_the_workspaces_keeps_only_the_new_ones_and_ignores_unknown_ids(aufbau):
    recht, physik = aufbau["ws"]
    repo.set_code_workspaces(aufbau["code_id"], [recht])
    repo.set_code_workspaces(aufbau["code_id"], [physik, 999_999_999])

    zugeordnet = repo.workspaces_by_code()[aufbau["code_id"]]
    assert [w["id"] for w in zugeordnet] == [physik]
    assert zugeordnet[0]["owner_id"] == aufbau["besitzer"]


def test_a_deleted_workspace_drops_out_of_the_code(verbindung, aufbau):
    recht, physik = aufbau["ws"]
    repo.set_code_workspaces(aufbau["code_id"], [recht, physik])
    with verbindung() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM aia_workspaces WHERE id = %s", (recht,))
        conn.commit()

    assert [w["id"] for w in repo.workspaces_by_code()[aufbau["code_id"]]] == [physik]


def _suche(query="", user_ids=(), rollen=("admin", "staff")):
    return repo.search_workspace_owners(
        query=query, user_ids=list(user_ids), system_roles=list(rollen),
        custom_role_ids=[], admin_email="", limit=20,
    )


def test_the_owner_search_finds_the_owner_with_both_workspaces(aufbau):
    kennung = repo.get_code_by_id(aufbau["code_id"])["code"].split("-")[-1].lower()
    for query in (f"ws.besitzer.{kennung}", f"Recht {kennung}"):
        treffer = [b for b in _suche(query) if b["user_id"] == aufbau["besitzer"]]
        assert len(treffer) == 1
        assert sorted(w["id"] for w in treffer[0]["workspaces"]) == sorted(aufbau["ws"])


def test_the_owner_search_by_id_and_the_rights_filter(aufbau):
    assert [b["user_id"] for b in _suche(user_ids=[aufbau["besitzer"]])] == [aufbau["besitzer"]]
    assert _suche(user_ids=[aufbau["besitzer"]], rollen=("user",)) == []


def test_wildcards_in_the_search_are_taken_literally(aufbau):
    assert [b for b in _suche("%") if b["user_id"] == aufbau["besitzer"]] == []


def test_the_user_ids_of_a_code(aufbau):
    assert sorted(repo.list_user_ids_for_code(aufbau["code_id"])) == sorted(aufbau["konten"])
