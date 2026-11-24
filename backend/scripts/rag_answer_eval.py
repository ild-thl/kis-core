"""Answer benchmark: is the fact also in what the reader gets to read?"""
import json
import os
import re
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import urllib.request

import psycopg2.extras

from src.core.db.pool import get_connection

API = os.environ.get("ASKF_API", "http://localhost:8000")
USER = os.environ.get("ASKF_USER", "a")
PASS = os.environ.get("ASKF_PASS", "a")

FAELLE = json.loads(
    (Path(__file__).parent / "rag_answer_cases.json").read_text(encoding="utf-8")
)


def _login() -> str:
    daten = json.dumps({"username": USER, "password": PASS}).encode()
    req = urllib.request.Request(f"{API}/auth/login", data=daten,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as antwort:
        keks = antwort.headers.get("set-cookie") or ""
    if "session=" not in keks:
        raise SystemExit(f"Anmeldung fehlgeschlagen fuer {USER!r}")
    return keks.split(";", 1)[0]


def _quellen(workspace_uuid: str) -> list[str]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """SELECT s.uuid FROM aia_sources s
                     JOIN aia_workspaces w ON w.id = s.workspace_id
                    WHERE w.uuid = %s AND s.status = 'ready' ORDER BY s.filename""",
                (workspace_uuid,),
            )
            return [r["uuid"] for r in cur.fetchall()]


def _frage(keks: str, workspace_uuid: str, frage: str,
           quellen: list[str]) -> tuple[str, dict[int, str]]:
    """The finished answer exactly as it appears in the chat."""
    daten = json.dumps({"question": frage, "active_source_ids": quellen}).encode()
    req = urllib.request.Request(
        f"{API}/ai-assistant/workspaces/{workspace_uuid}/chat",
        data=daten, headers={"Content-Type": "application/json", "Cookie": keks},
    )
    stuecke: list[str] = []
    qmap: dict[int, str] = {}
    with urllib.request.urlopen(req, timeout=600) as antwort:
        for roh in antwort:
            zeile = roh.decode("utf-8", "replace").strip()
            if not zeile.startswith("data: "):
                continue
            nutz = zeile[6:]
            if nutz == "[DONE]":
                continue
            try:
                o = json.loads(nutz)
            except Exception:                                   # noqa: BLE001
                continue
            if isinstance(o, dict):
                for schluessel in ("qmap", "source_qmap"):
                    for eintrag in (o.get(schluessel) or []):
                        qmap[eintrag["qnum"]] = eintrag["filename"]
                if o.get("done") and isinstance(o.get("answer"), str):
                    return o["answer"], qmap
                if isinstance(o.get("token"), str):
                    stuecke.append(o["token"])
    return "".join(stuecke), qmap


def main() -> int:
    keks = _login()
    quellen_cache: dict[str, list[str]] = {}
    ok = 0
    for fall in FAELLE:
        ws = fall["workspace"]
        if ws not in quellen_cache:
            quellen_cache[ws] = _quellen(ws)
        antwort, qmap = _frage(keks, ws, fall["frage"], quellen_cache[ws])
        klein = antwort.lower()
        treffer = [e for e in fall.get("erwartet", []) if e.lower() in klein]
        verstoss = [v for v in fall.get("verboten", []) if v.lower() in klein]
        fehlende_quellen: list[str] = []
        if fall.get("alle_quellen"):
            zitiert = {int(n) for n in re.findall(r"\[(\d+),", antwort)}
            fehlende_quellen = [qmap[q] for q in sorted(qmap) if q not in zitiert]
        gut = (not verstoss and not fehlende_quellen
               and (bool(treffer) or not fall.get("erwartet")))
        ok += 1 if gut else 0
        print(f"\n{'OK  ' if gut else 'FEHLT'} {fall['id']}")
        print(f"      Frage:    {fall['frage']}")
        if not treffer and fall.get("erwartet"):
            print(f"      Erwartet: eines von {fall['erwartet']}  -> KEINES gefunden")
        if verstoss:
            print(f"      Verboten: {verstoss} steht drin")
        if fall.get("alle_quellen"):
            print(f"      Quellen:  {len(qmap) - len(fehlende_quellen)}/{len(qmap)} belegt"
                  + (f"  -> fehlt: {fehlende_quellen}" if fehlende_quellen else ""))
        print(f"      Antwort:  {' '.join(antwort.split())[:400]}")
    print(f"\n{'-' * 70}\nAntworten in Ordnung: {ok}/{len(FAELLE)}")
    return 0 if ok == len(FAELLE) else 1


if __name__ == "__main__":
    sys.exit(main())
