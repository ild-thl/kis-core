"""An expired test account is locked first and only deleted once the grace period ran out."""

import os
import uuid as uuid_modul
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

psycopg2 = pytest.importorskip("psycopg2")

from src.features.access_codes import repository as repo  # noqa: E402


# --- The query against the real schema ---------------------------------------


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
    """The tables as init_db builds them."""
    from src.core.db.schema import init_db
    init_db()
    return verbindung


@pytest.fixture
def konto_bauen(schema):
    """Makes an account with a chosen deadline and clears it away afterwards."""
    angelegt: list[tuple[int, int | None]] = []

    def _bauen(*, abgelaufen_vor_tagen: float | None, mit_code: bool = True):
        kennung = uuid_modul.uuid4().hex[:8]
        code_id = None
        if mit_code:
            code_id = repo.create_code(
                code=f"KIS-TEST-{kennung.upper()}",
                label="Testrunde Schonfrist",
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
                    "VALUES (%s, %s, %s, 0, 'user') RETURNING id",
                    (f"test.schonfrist.{kennung}", "Test Schonfrist",
                     f"test.schonfrist.{kennung}@demo.kis.local"),
                )
                user_id = cur.fetchone()[0]
            conn.commit()
        frist = (
            None if abgelaufen_vor_tagen is None
            else datetime.now() - timedelta(days=abgelaufen_vor_tagen)
        )
        repo.set_user_access(user_id, expires_at=frist, code_id=code_id)
        angelegt.append((user_id, code_id))
        return user_id

    yield _bauen

    with schema() as conn:
        with conn.cursor() as cur:
            for user_id, code_id in angelegt:
                cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
                if code_id is not None:
                    cur.execute("DELETE FROM access_codes WHERE id = %s", (code_id,))
        conn.commit()


def test_an_account_inside_the_grace_period_stays(konto_bauen):
    """Twenty-nine days after the deadline the admin still needs it for the evaluation."""
    user_id = konto_bauen(abgelaufen_vor_tagen=29)

    assert user_id not in repo.list_accounts_due_for_deletion(30)


def test_an_account_past_the_grace_period_is_due(konto_bauen):
    user_id = konto_bauen(abgelaufen_vor_tagen=31)

    assert user_id in repo.list_accounts_due_for_deletion(30)


def test_an_account_exactly_on_the_boundary_is_due(konto_bauen):
    """Thirty days plus a minute counts, so the job never stalls on a rounding edge."""
    user_id = konto_bauen(abgelaufen_vor_tagen=30 + 1 / 1440)

    assert user_id in repo.list_accounts_due_for_deletion(30)


def test_an_account_without_a_code_is_never_due(konto_bauen):
    """Only accounts a code created may be swept, a normal account never."""
    user_id = konto_bauen(abgelaufen_vor_tagen=400, mit_code=False)

    assert user_id not in repo.list_accounts_due_for_deletion(30)


def test_an_account_without_a_deadline_is_never_due(konto_bauen):
    user_id = konto_bauen(abgelaufen_vor_tagen=None)

    assert user_id not in repo.list_accounts_due_for_deletion(30)


def test_a_longer_grace_period_spares_an_account_the_short_one_would_take(konto_bauen):
    user_id = konto_bauen(abgelaufen_vor_tagen=31)

    assert user_id in repo.list_accounts_due_for_deletion(30)
    assert user_id not in repo.list_accounts_due_for_deletion(90)


# --- The switch that turns the sweep off -------------------------------------


def test_a_grace_period_of_zero_asks_the_database_nothing(monkeypatch):
    """Zero is the emergency exit, it must not even reach the database."""
    def _explodieren():
        raise AssertionError("bei 0 Tagen darf keine Abfrage laufen")

    monkeypatch.setattr(repo, "get_connection", _explodieren)

    assert repo.list_accounts_due_for_deletion(0) == []


def test_a_negative_grace_period_deletes_nothing(monkeypatch):
    def _explodieren():
        raise AssertionError("bei negativen Tagen darf keine Abfrage laufen")

    monkeypatch.setattr(repo, "get_connection", _explodieren)

    assert repo.list_accounts_due_for_deletion(-5) == []


# --- The nightly job ---------------------------------------------------------


@pytest.fixture
def job():
    from src.tasks.cleanup_tasks import run_delete_expired_access_accounts
    return run_delete_expired_access_accounts


def _laufen_lassen(job, *, faellig, einstellung="30", loeschen=None, ordner=None):
    """Runs the job with the database and the storage out of the way."""
    with patch.object(repo, "list_accounts_due_for_deletion", return_value=faellig) as abfrage, \
         patch("src.features.access_codes.retention.get_setting", return_value=einstellung), \
         patch("src.features.admin.repository.user_delete.delete_user_completely",
               side_effect=loeschen) as konto_weg, \
         patch("src.storage.delete_user_folder", side_effect=ordner or (lambda _: 3)) as dateien_weg:
        anzahl = job()
    return anzahl, abfrage, konto_weg, dateien_weg


def test_the_job_deletes_every_due_account(job):
    anzahl, _, konto_weg, dateien_weg = _laufen_lassen(job, faellig=[11, 12, 13])

    assert anzahl == 3
    assert [ruf.args[0] for ruf in konto_weg.call_args_list] == [11, 12, 13]
    assert [ruf.args[0] for ruf in dateien_weg.call_args_list] == [11, 12, 13]


def test_the_job_takes_the_grace_period_from_the_settings(job):
    _, abfrage, _, _ = _laufen_lassen(job, faellig=[], einstellung="90")

    assert abfrage.call_args.args[0] == 90


def test_the_job_falls_back_to_thirty_days_on_a_broken_setting(job):
    """A typo in the admin field must not turn the sweep into something wilder."""
    _, abfrage, _, _ = _laufen_lassen(job, faellig=[], einstellung="dreissig")

    assert abfrage.call_args.args[0] == 30


def test_the_job_keeps_going_when_one_account_fails(job):
    def _zweites_bricht(user_id):
        if user_id == 12:
            raise RuntimeError("Fremdschluessel haengt")

    anzahl, _, konto_weg, _ = _laufen_lassen(job, faellig=[11, 12, 13],
                                             loeschen=_zweites_bricht)

    assert anzahl == 2, "das kaputte Konto zaehlt nicht, die anderen schon"
    assert [ruf.args[0] for ruf in konto_weg.call_args_list] == [11, 12, 13]


def test_the_job_counts_an_account_whose_files_fail(job):
    """The row is gone, so the account counts even when the folder resisted."""
    def _dateien_brechen(_user_id):
        raise OSError("Speicher nicht erreichbar")

    anzahl, _, _, _ = _laufen_lassen(job, faellig=[11], ordner=_dateien_brechen)

    assert anzahl == 1


def test_the_job_survives_a_dead_database(job):
    with patch.object(repo, "list_accounts_due_for_deletion",
                      side_effect=RuntimeError("keine Verbindung")), \
         patch("src.features.access_codes.retention.get_setting", return_value="30"):
        assert job() == 0


# --- The nightly slot --------------------------------------------------------


def test_the_sweep_is_in_the_beat_plan_and_runs_at_night():
    """Deleting is irreversible, so it runs once a night and not hourly like the lock."""
    from celery.schedules import crontab

    from src.celery_app import celery_app

    eintrag = celery_app.conf.beat_schedule["cleanup-delete-expired-access-accounts"]

    assert eintrag["task"] == "cleanup.delete_expired_access_accounts"
    assert isinstance(eintrag["schedule"], crontab), "ein Intervall wuerde tagsueber loeschen"
    assert eintrag["options"] == {"queue": "general"}


def test_the_sweep_runs_after_the_nightly_backup():
    """What gets deleted must have been in a backup before."""
    from src.celery_app import celery_app

    sicherung = celery_app.conf.beat_schedule["backup-database"]["schedule"]
    loeschen = celery_app.conf.beat_schedule["cleanup-delete-expired-access-accounts"]["schedule"]

    assert min(loeschen.hour) > min(sicherung.hour), "sonst loescht der Job vor der Sicherung"


# --- The date the admin gets to see ------------------------------------------


def test_the_deletion_date_is_the_deadline_plus_the_grace_period():
    from src.features.access_codes.service import deletion_due_at

    assert deletion_due_at(
        access_expires_at=datetime(2026, 9, 1, 12, 0), grace_days=30
    ) == datetime(2026, 10, 1, 12, 0)


def test_an_account_without_a_deadline_has_no_deletion_date():
    from src.features.access_codes.service import deletion_due_at

    assert deletion_due_at(access_expires_at=None, grace_days=30) is None


def test_a_switched_off_sweep_shows_no_deletion_date():
    """With the grace period at zero nothing is ever deleted, so no date may be promised."""
    from src.features.access_codes.service import deletion_due_at

    assert deletion_due_at(access_expires_at=datetime(2026, 9, 1, 12, 0), grace_days=0) is None
