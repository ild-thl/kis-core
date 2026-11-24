"""Takes finished summary, presentation and podcast runs over as the demo results, safe to run again.

    docker exec askf-backend python scripts/demo_ergebnis_uebernehmen.py --ziel /tmp/demo <job_uuid> [...]
    docker cp askf-backend:/tmp/demo/. backend/demo/

The container mounts demo/ read only, so the results go to a folder of its own first.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from src import database as db  # noqa: E402
from src.features.podcast import store as podcast_store  # noqa: E402
from src.features.praesentation import store  # noqa: E402
from src.features.summary.models import INSTRUCTIONS_FILE  # noqa: E402
from src.routes.jobs._shared import _dt  # noqa: E402
from src.routes.praesentation.media import _bildplaetze  # noqa: E402
from src.services import sources  # noqa: E402
from src.services.job_statistik import angaben_lesen  # noqa: E402
from src.storage import get_file, get_job_file, job_file_exists, load_result_meta  # noqa: E402

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"
FERTIG = ("completed", "success")


def _schreiben(pfad: Path, daten: bytes) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(daten)


def zusammenfassung(job: dict, workspace: str, ziel: Path) -> str:
    """The Markdown and Word result into the folder of its template, the material into demo.json."""
    uid, uuid = job["user_id"], job["job_uuid"]
    slug = json.loads(get_job_file(uid, uuid, "summary_params.json"))["template_slug"]
    ordner = ziel / "zusammenfassung" / slug
    shutil.rmtree(ordner, ignore_errors=True)
    stamm = Path(job["result_filename"] or f"{slug}.md").stem
    _schreiben(ordner / f"{stamm}.md", get_file(job["result_path"]))
    _schreiben(ordner / f"{stamm}.docx", get_job_file(uid, uuid, "output.docx"))
    anweisung = get_job_file(uid, uuid, INSTRUCTIONS_FILE).decode() if job_file_exists(uid, uuid, INSTRUCTIONS_FILE) else ""
    material = {"workspace": workspace, "dateien": [q.dateiname for q in sources.load_sources(uid, uuid)],
                "anweisung": anweisung}
    (ziel / "zusammenfassung" / "demo.json").write_text(json.dumps(material, ensure_ascii=False, indent=2),
                                                            encoding="utf-8")
    return f"Zusammenfassung {slug}"


def praesentation(job: dict, workspace: str, ziel: Path) -> str:
    """Outline, slides, pictures, previews and the file, as the demo route reads them."""
    uid, uuid = job["user_id"], job["job_uuid"]
    params = store.load_params(uid, uuid)
    outline = store.load_outline(uid, uuid)
    slides = store.load_slides(uid, uuid)
    ordner = ziel / "praesentation"
    shutil.rmtree(ordner, ignore_errors=True)
    for s in slides:
        if store.has_preview(uid, uuid, s.id):
            _schreiben(ordner / store.preview_name(s.id), store.get_preview(uid, uuid, s.id))
        for slot in _bildplaetze(s):
            if store.has_image(uid, uuid, s.id, slot):
                _schreiben(ordner / store.image_name(s.id, slot), store.get_image(uid, uuid, s.id, slot))
    _schreiben(ordner / store.DECK_FILE, store.get_deck(uid, uuid))

    dateien: list[str] = []
    if params and params.workspace_id:
        workspace = (db.get_aia_workspace_by_id(params.workspace_id) or {}).get("title") or workspace
        namen = {q["uuid"]: q["filename"] for q in db.get_aia_sources_by_workspace(params.workspace_id)}
        dateien = [namen[u] for u in params.source_uuids if u in namen]
    elif params and params.source_label:
        # Without the workspace only the joined names are left, the way sources.label writes them.
        dateien = params.source_label.split(", ")
    ansicht = {
        "params": params.model_dump() if params else None,
        "outline": outline.model_dump() if outline else None,
        "slides": [s.model_dump() for s in slides],
        "workspace": workspace,
        "dateien": dateien,
    }
    (ordner / "ansicht.json").write_text(json.dumps(ansicht, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Präsentation mit {len(slides)} Folien"


def podcast(job: dict, workspace: str, ziel: Path) -> str:
    """Cast, script, the audio of every contribution and the finished file."""
    uid, uuid = job["user_id"], job["job_uuid"]
    params = podcast_store.load_params(uid, uuid)
    zeilen = podcast_store.load_lines(uid, uuid)
    ordner = ziel / "podcast"
    shutil.rmtree(ordner, ignore_errors=True)
    for z in zeilen:
        ton = podcast_store.get_line_audio(uid, uuid, z.id)
        if ton:
            _schreiben(ordner / podcast_store.audio_name(z.id), ton)
    _schreiben(ordner / "podcast.mp3", get_file(job["result_path"]))
    # The podcast keeps only the joined names, the way sources.label writes them.
    dateien = params.source_label.split(", ") if params and params.source_label else []
    ansicht = {
        "params": params.model_dump() if params else None,
        "lines": [z.model_dump() for z in zeilen],
        "seconds": (load_result_meta(uid, uuid) or {}).get("seconds"),
        "workspace": workspace,
        "dateien": dateien,
        "angaben": angaben_lesen(job),
        "erstellt": _dt(job.get("created_at")),
    }
    (ordner / "ansicht.json").write_text(json.dumps(ansicht, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Podcast mit {len(zeilen)} Beiträgen"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("jobs", nargs="+", help="UUIDs fertiger Läufe")
    parser.add_argument("--workspace", default="Projektmanagement",
                        help="Name des Workspace, falls der Lauf ihn nicht kennt")
    parser.add_argument("--ziel", type=Path, default=DEMO_DIR, help="Ordner, in den die Ergebnisse gehen")
    args = parser.parse_args()

    for uuid in args.jobs:
        job = db.get_job(uuid)
        if not job or job["status"] not in FERTIG:
            print(f"{uuid}: kein fertiger Lauf", file=sys.stderr)
            return 1
        if job["tool"] == "summary":
            print(f"{uuid}: {zusammenfassung(job, args.workspace, args.ziel)}")
        elif job["tool"] == "praesentation":
            print(f"{uuid}: {praesentation(job, args.workspace, args.ziel)}")
        elif job["tool"] == "podcast":
            print(f"{uuid}: {podcast(job, args.workspace, args.ziel)}")
        else:
            print(f"{uuid}: {job['tool']} hat keine Demo", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
