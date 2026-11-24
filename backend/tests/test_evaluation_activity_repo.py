"""Whether an account has ever done anything beyond logging in, checked against the real schema."""

import os
import uuid as uuid_modul
from datetime import datetime, timedelta

import pytest

psycopg2 = pytest.importorskip("psycopg2")

from src.features.evaluation import repository as repo  # noqa: E402


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
    """The tables as init_db builds them, this is what the query rests on."""
    from src.core.db.schema import init_db
    init_db()
    return verbindung


@pytest.fixture
def konto(schema):
    """A bare account, no tour, no jobs, no workspace, nothing."""
    kennung = uuid_modul.uuid4().hex[:8]
    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, display_name, email, active, role) "
                "VALUES (%s, %s, %s, 1, 'user') RETURNING id",
                (f"test.activity.{kennung}", "Test Aktivitaet",
                 f"test.activity.{kennung}@demo.kis.local"),
            )
            user_id = cur.fetchone()[0]
        conn.commit()
    yield user_id
    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM aia_messages WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM aia_sources WHERE workspace_id IN "
                        "(SELECT id FROM aia_workspaces WHERE user_id = %s)", (user_id,))
            cur.execute("DELETE FROM aia_workspaces WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM jobs WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()


def _neue_werkstatt(schema, user_id: int) -> int:
    kennung = uuid_modul.uuid4().hex[:8]
    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO aia_workspaces (uuid, user_id, title) VALUES (%s, %s, %s) RETURNING id",
                (f"ws-{kennung}", user_id, "Testmodul"),
            )
            workspace_id = cur.fetchone()[0]
        conn.commit()
    return workspace_id


def test_a_fresh_account_has_no_activity(schema, konto):
    assert repo.has_platform_activity(konto) is False


def test_a_completed_tour_counts_as_activity(schema, konto):
    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET tour_seen_at = NOW() WHERE id = %s", (konto,))
        conn.commit()
    assert repo.has_platform_activity(konto) is True


def test_a_job_of_any_tool_counts_as_activity(schema, konto):
    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (job_uuid, user_id, tool) VALUES (%s, %s, %s)",
                (f"job-{uuid_modul.uuid4().hex[:8]}", konto, "podcast"),
            )
        conn.commit()
    assert repo.has_platform_activity(konto) is True


def test_a_workspace_without_any_upload_does_not_count(schema, konto):
    _neue_werkstatt(schema, konto)
    assert repo.has_platform_activity(konto) is False


def test_an_own_workspace_with_an_uploaded_source_counts(schema, konto):
    workspace_id = _neue_werkstatt(schema, konto)
    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO aia_sources (uuid, workspace_id, filename, file_path, file_type) "
                "VALUES (%s, %s, %s, %s, %s)",
                (f"src-{uuid_modul.uuid4().hex[:8]}", workspace_id, "skript.pdf", "/tmp/skript.pdf", "pdf"),
            )
        conn.commit()
    assert repo.has_platform_activity(konto) is True


def test_sending_a_prompt_counts_even_in_someone_elses_workspace(schema, konto):
    """The demo module belongs to someone else, asking a question there still counts."""
    kennung = uuid_modul.uuid4().hex[:8]
    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, display_name, email, active, role) "
                "VALUES (%s, %s, %s, 1, 'user') RETURNING id",
                (f"test.owner.{kennung}", "Testbesitzer", f"test.owner.{kennung}@demo.kis.local"),
            )
            owner_id = cur.fetchone()[0]
        conn.commit()
    workspace_id = _neue_werkstatt(schema, owner_id)
    try:
        with schema() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO aia_messages (workspace_id, user_id, role, content) VALUES (%s, %s, 'user', %s)",
                    (workspace_id, konto, "Was steht auf Seite 3?"),
                )
            conn.commit()
        assert repo.has_platform_activity(konto) is True
    finally:
        with schema() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM aia_messages WHERE workspace_id = %s", (workspace_id,))
                cur.execute("DELETE FROM aia_workspaces WHERE id = %s", (workspace_id,))
                cur.execute("DELETE FROM users WHERE id = %s", (owner_id,))
            conn.commit()


def test_an_assistant_reply_alone_does_not_count(schema, konto):
    """Only what the person themselves typed counts, not an answer that happens to carry their id."""
    workspace_id = _neue_werkstatt(schema, konto)
    with schema() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO aia_messages (workspace_id, user_id, role, content) VALUES (%s, %s, 'assistant', %s)",
                (workspace_id, konto, "Hallo, wie kann ich helfen?"),
            )
        conn.commit()
    assert repo.has_platform_activity(konto) is False
