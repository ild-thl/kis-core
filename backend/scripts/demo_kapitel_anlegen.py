"""Puts the demo module's materials into their chapters, safe to run again.

    docker exec askf-backend python scripts/demo_kapitel_anlegen.py [--workspace <uuid>]
"""

import argparse
import re
import sys
import uuid as uuid_lib

sys.path.insert(0, "/app")

from src import database as db  # noqa: E402

DEMO_WORKSPACE_UUID = "6f2d916b-94a3-403a-ab4d-9000699e5ef0"
EINHEITEN = [
    "Grundlagen",
    "Projektstart",
    "Struktur und Aufwand",
    "Ablauf und Termine",
    "Steuerung",
    "Team und Methoden",
]
BEGLEITMATERIAL = "Begleitmaterial"
_EINHEIT_MUSTER = re.compile(r"^DEMO_(?:Vorlesung|Folien)_0(\d)_|^DEMO_Skript_Kapitel_(\d)_")


def kapitelnamen() -> list[str]:
    """All chapters in list order, the units first, the extras last."""
    return [f"Einheit {n}: {titel}" for n, titel in enumerate(EINHEITEN, start=1)] + [BEGLEITMATERIAL]


def kapitel_fuer(dateiname: str) -> str | None:
    """Chapter name for a demo file, None for anything that is not demo material."""
    treffer = _EINHEIT_MUSTER.match(dateiname)
    if treffer:
        nummer = int(treffer.group(1) or treffer.group(2))
        if 1 <= nummer <= len(EINHEITEN):
            return f"Einheit {nummer}: {EINHEITEN[nummer - 1]}"
    if dateiname.startswith("DEMO_"):
        return BEGLEITMATERIAL
    return None


def kapitel_anlegen(workspace_uuid: str) -> dict[str, int]:
    """Creates the missing chapters and moves every demo file, returns a count per chapter."""
    workspace = db.get_aia_workspace(workspace_uuid)
    if workspace is None:
        raise SystemExit(f"Kein Modul mit der UUID {workspace_uuid}")

    vorhanden = {c["name"]: c for c in db.get_aia_chapters_by_workspace(workspace["id"])}
    for name in kapitelnamen():
        if name not in vorhanden:
            vorhanden[name] = db.create_aia_chapter(workspace["id"], uuid_lib.uuid4().hex, name)
            print(f"angelegt: {name}")

    zaehler: dict[str, int] = {name: 0 for name in kapitelnamen()}
    for quelle in db.get_aia_sources_by_workspace(workspace["id"]):
        name = kapitel_fuer(quelle["filename"])
        if name is None:
            print(f"uebersprungen (kein Demo-Material): {quelle['filename']}")
            continue
        ziel = vorhanden[name]
        if quelle.get("chapter_id") != ziel["id"]:
            db.set_aia_source_chapter(quelle["uuid"], ziel["id"])
        zaehler[name] += 1
    return zaehler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", default=DEMO_WORKSPACE_UUID, help="UUID des Demo-Moduls")
    args = parser.parse_args()
    for name, anzahl in kapitel_anlegen(args.workspace).items():
        print(f"{anzahl:2d}  {name}")


if __name__ == "__main__":
    main()
