"""Deleting a code must never take an account with it, this checks the real schema."""

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
def schema(verbindung):
    """The tables as init_db builds them, this is what the promise rests on."""
    from src.core.db.schema import init_db
    init_db()
    return verbindung


@pytest.fixture
def konto_am_code(schema):
    """A code plus an account created by it, both disappear afterwards."""
    kennung = uuid_modul.uuid4().hex[:8]
    code_id = repo.create_code(
        code=f"ASKF-TEST-{kennung.upper()}",
        label="Testrunde Loeschen",
        role="user",
        custom_role_id=None,
        max_uses=5,
        valid_until=datetime.now() + timedelta(days=30),
        access_hours=336,
        show_credentials=True,
        show_evaluation=False,
        created_by=0,
    )
    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, display_name, email, active, role) "
                "VALUES (%s, %s, %s, 1, 'user') RETURNING id",
                (f"test.loeschen.{kennung}", "Test Loeschen",
                 f"test.loeschen.{kennung}@demo.askfrancis.local"),
            )
            user_id = cur.fetchone()[0]
        conn.commit()
    frist = datetime.now() + timedelta(days=14)
    repo.set_user_access(user_id, expires_at=frist, code_id=code_id)
    yield code_id, user_id, frist
    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
            cur.execute("DELETE FROM access_codes WHERE id = %s", (code_id,))
        conn.commit()


def test_the_schema_has_access_hours_not_access_days(schema):
    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'access_codes' AND column_name IN "
                "('access_days', 'access_hours', 'show_credentials')"
            )
            spalten = {zeile[0] for zeile in cur.fetchall()}
    assert spalten == {"access_hours", "show_credentials"}, \
        "die alte Tages-Spalte muss nach der Migration verschwunden sein"


def test_an_old_install_gets_the_evaluation_column_switched_off(schema):
    """The column has to arrive by migration too, and never switch itself on."""
    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_default, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'access_codes' AND column_name = 'show_evaluation'"
            )
            zeile = cur.fetchone()
    assert zeile is not None, "die Spalte fehlt, alte Installationen brechen"
    vorgabe, nullbar = zeile
    assert "false" in vorgabe.lower(), "bestehende Codes duerfen die Evaluation nicht ploetzlich zeigen"
    assert nullbar == "NO"


def test_the_switch_survives_the_round_trip_through_the_real_schema(schema, konto_am_code):
    code_id, user_id, _ = konto_am_code

    assert repo.shows_evaluation(user_id) is False

    repo.update_code(
        code_id,
        label="Tag der Lehre",
        role="user",
        custom_role_id=None,
        max_uses=50,
        valid_until=datetime.now() + timedelta(days=1),
        access_hours=12,
        show_credentials=True,
        show_evaluation=True,
    )

    assert repo.shows_evaluation(user_id) is True


def test_deleting_the_code_keeps_the_account_and_its_deadline(schema, konto_am_code):
    code_id, user_id, frist = konto_am_code

    assert repo.delete_code(code_id) is True

    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT active, access_expires_at, access_code_id FROM users WHERE id = %s",
                (user_id,),
            )
            zeile = cur.fetchone()

    assert zeile is not None, "Das Konto darf mit dem Code nicht verschwinden"
    aktiv, ablauf, verweis = zeile
    assert aktiv == 1, "Das Konto bleibt eingeschaltet"
    assert verweis is None, "Der Verweis wird geleert, ON DELETE SET NULL"
    assert abs((ablauf - frist).total_seconds()) < 1, "Die Frist steht unveraendert"


def test_set_users_active_switches_code_accounts_but_never_others(schema, konto_am_code):
    code_id, user_id, _ = konto_am_code
    kennung = uuid_modul.uuid4().hex[:8]
    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, display_name, email, active, role) "
                "VALUES (%s, 'Echt', %s, 1, 'user') RETURNING id",
                (f"test.echt.{kennung}", f"test.echt.{kennung}@demo.askfrancis.local"),
            )
            echt_id = cur.fetchone()[0]
        conn.commit()
    try:
        assert repo.set_users_active([user_id, echt_id], False) == [user_id]
        with schema() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, active FROM users WHERE id = ANY(%s) ORDER BY id",
                            ([user_id, echt_id],))
                zustand = dict(cur.fetchall())
        assert zustand == {user_id: 0, echt_id: 1}
    finally:
        with schema() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s", (echt_id,))
            conn.commit()
