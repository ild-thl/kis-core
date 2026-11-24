"""Inventory of orphaned files, rather overlook than report when in doubt."""

from src.services import storage_audit as audit

# Names as in production, uuid4().hex.
QUELLE = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
QUELLE2 = "0a1b2c3d4e5f60718293a4b5c6d7ffff"

WS = "users/7/aia/workspaces/w1"
JOB = "users/7/jobs/j1"


def _bestand(**kw):
    """Known inventory from the database, empty by default."""
    return audit.Bestand(
        job_praefixe=set(kw.get("jobs", [])),
        workspace_praefixe=set(kw.get("workspaces", [])),
        quell_basen=kw.get("quellen", {}),
    )


# ─── What is fine ──────────────────────────────────────────────────────────

def test_eine_quelle_mit_eintrag_gilt_als_in_ordnung():
    keys = [
        f"{WS}/sources/{QUELLE}.mp4",
        f"{WS}/sources/{QUELLE}_transcript.txt",
        f"{WS}/sources/{QUELLE}_transcript.de.vtt",
    ]
    bestand = _bestand(workspaces=[WS], quellen={WS: {f"{WS}/sources/{QUELLE}"}})

    assert audit.finde_verwaiste(keys, bestand) == {}


def test_ein_job_mit_eintrag_gilt_als_in_ordnung():
    keys = [f"{JOB}/output.mp4", f"{JOB}/audio/slide_000.mp3", f"{JOB}/meta.json"]

    assert audit.finde_verwaiste(keys, _bestand(jobs=[JOB])) == {}


def test_andere_bereiche_werden_gar_nicht_erst_angefasst():
    """``tmp/`` and ``backups/`` are cleaned by storage itself over time."""
    keys = ["tmp/pptx/abc.pptx", "backups/daily/askfrancis-2026-07-30.dump"]

    assert audit.finde_verwaiste(keys, _bestand()) == {}


def test_gesprochene_beispielsaetze_gehoeren_nicht_hierher():
    """The audio files have their own cleanup rule and stay out."""
    keys = [f"aia/speech/ab/{'ab' + 'c' * 62}.mp3"]

    assert audit.finde_verwaiste(keys, _bestand()) == {}


# ─── What is orphaned ──────────────────────────────────────────────────────

def test_transkript_ohne_quelle_ist_verwaist():
    """The actual case: the source was deleted, the transcript was not."""
    keys = [f"{WS}/sources/{QUELLE}_transcript.txt", f"{WS}/sources/{QUELLE}_transcript.de.vtt"]
    bestand = _bestand(workspaces=[WS], quellen={WS: set()})

    assert audit.finde_verwaiste(keys, bestand) == {
        "quelle": [f"{WS}/sources/{QUELLE}_transcript.de.vtt",
                   f"{WS}/sources/{QUELLE}_transcript.txt"],
    }


def test_ein_ganzer_workspace_ohne_eintrag_ist_verwaist():
    keys = [f"{WS}/sources/{QUELLE}.mp4", f"{WS}/sources/{QUELLE}_transcript.txt"]

    verwaist = audit.finde_verwaiste(keys, _bestand())

    assert list(verwaist) == ["workspace"]
    assert len(verwaist["workspace"]) == 2


def test_ein_job_ohne_eintrag_ist_verwaist():
    keys = [f"{JOB}/output.mp4", f"{JOB}/audio/slide_000.mp3"]

    verwaist = audit.finde_verwaiste(keys, _bestand())

    assert list(verwaist) == ["job"]
    assert len(verwaist["job"]) == 2


def test_die_nachbarquelle_bleibt_in_ordnung():
    """An orphaned source must not drag the neighbouring one in with it."""
    keys = [
        f"{WS}/sources/{QUELLE}.mp4",
        f"{WS}/sources/{QUELLE2}_transcript.txt",
    ]
    bestand = _bestand(workspaces=[WS], quellen={WS: {f"{WS}/sources/{QUELLE}"}})

    assert audit.finde_verwaiste(keys, bestand) == {
        "quelle": [f"{WS}/sources/{QUELLE2}_transcript.txt"],
    }


def test_ein_fremder_ordner_im_workspace_wird_gemeldet_aber_nicht_eingeordnet():
    """An old folder is reported, but separately."""
    keys = [f"{WS}/outputs/mindmap.json"]
    bestand = _bestand(workspaces=[WS], quellen={WS: set()})

    assert audit.finde_verwaiste(keys, bestand) == {
        "unbekannt": [f"{WS}/outputs/mindmap.json"],
    }


def test_ein_schluessel_ausserhalb_des_schemas_wird_nie_als_verwaist_gemeldet():
    keys = ["users/7/irgendwas.txt", "users/kaputt/jobs/j1/output.mp4"]

    verwaist = audit.finde_verwaiste(keys, _bestand())

    assert list(verwaist) == ["unbekannt"]
    assert len(verwaist["unbekannt"]) == 2


# ─── Absolute paths without S3 ─────────────────────────────────────────────

def test_absolute_pfade_werden_auf_schluessel_zurueckgefuehrt():
    """Both sides have to arrive at the same path form."""
    wurzel = "/app/storage/"
    keys = [f"{wurzel}{WS}/sources/{QUELLE}.mp4"]
    bestand = _bestand(workspaces=[WS], quellen={WS: {f"{WS}/sources/{QUELLE}"}})

    assert audit.finde_verwaiste(keys, bestand, wurzel=wurzel) == {}


# ─── Protection against running uploads ────────────────────────────────────

def test_frische_dateien_werden_zurueckgehalten():
    """A running upload has no row yet and needs the grace period."""
    jetzt = 1_000_000.0
    alter = {"alt.txt": jetzt - 90_000, "frisch.txt": jetzt - 60}

    behalten, zurueck = audit.trenne_nach_alter(
        ["alt.txt", "frisch.txt"], alter.get, mindest_stunden=24, jetzt=jetzt,
    )

    assert behalten == ["alt.txt"]
    assert zurueck == ["frisch.txt"]


def test_ohne_lesbaren_zeitstempel_wird_zurueckgehalten():
    """Do not delete when in doubt."""
    behalten, zurueck = audit.trenne_nach_alter(
        ["ratlos.txt"], lambda p: None, mindest_stunden=24, jetzt=1_000_000.0,
    )

    assert behalten == []
    assert zurueck == ["ratlos.txt"]


def test_ohne_schranke_wird_nichts_zurueckgehalten():
    behalten, zurueck = audit.trenne_nach_alter(
        ["a", "b"], lambda p: None, mindest_stunden=0, jetzt=1_000_000.0,
    )

    assert behalten == ["a", "b"]
    assert zurueck == []


# ─── Zusammenfassung ───────────────────────────────────────────────────────

def test_die_zusammenfassung_zaehlt_je_art():
    verwaist = {"quelle": ["a", "b"], "job": ["c"]}

    assert audit.zusammenfassen(verwaist) == {"quelle": 2, "job": 1, "gesamt": 3}


def test_die_zusammenfassung_ist_bei_nichts_leer():
    assert audit.zusammenfassen({}) == {"gesamt": 0}
