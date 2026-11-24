"""Builds one readable Markdown trace of a summary job from its files and its Langfuse calls.

For a developer inspecting a run, not a shipped feature: no download route, no translation.
Every model call already lands in Langfuse (the OpenAI-compatible client is Langfuse-wrapped),
tagged with the job's uuid as its session id, so this script only has to pull it back together
with what the job folder itself holds (sources, facts, outline, the finished text).

Run inside a container that can reach both job storage and Langfuse, for example:
    docker exec askf-celery-zsf python scripts/summary_trace.py <job_uuid> --out /tmp/trace.md
"""

import argparse
import json
import os
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import httpx

from src import database as db
from src.storage import get_job_file, job_file_exists

_ZAHL = lambda n: f"{n:,}".replace(",", ".")  # noqa: E731 - a one-line formatter, not a policy


def _read_json(user_id: int, job_uuid: str, name: str, default):
    if not job_file_exists(user_id, job_uuid, name):
        return default
    try:
        return json.loads(get_job_file(user_id, job_uuid, name).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return default


def _read_text(user_id: int, job_uuid: str, name: str) -> str | None:
    if not job_file_exists(user_id, job_uuid, name):
        return None
    return get_job_file(user_id, job_uuid, name).decode("utf-8")


def _langfuse_client() -> httpx.Client:
    host = os.environ.get("LANGFUSE_HOST", "http://askf-langfuse:3000").rstrip("/")
    auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
    return httpx.Client(base_url=host, auth=auth, timeout=30.0)


def fetch_calls(job_uuid: str) -> list[dict]:
    """Every model call of this job, in the order it happened, with its full input and output."""
    with _langfuse_client() as client:
        antwort = client.get("/api/public/traces", params={"sessionId": job_uuid, "limit": 100})
        antwort.raise_for_status()
        kurz = antwort.json()["data"]
        aufrufe = []
        for eintrag in kurz:
            voll = client.get(f"/api/public/traces/{eintrag['id']}")
            voll.raise_for_status()
            for beobachtung in voll.json().get("observations") or []:
                if beobachtung.get("type") == "GENERATION":
                    aufrufe.append(beobachtung)
    aufrufe.sort(key=lambda o: o.get("startTime") or "")
    return aufrufe


def _dauer(aufruf: dict) -> str:
    start, ende = aufruf.get("startTime"), aufruf.get("endTime")
    if not start or not ende:
        return "unbekannt"
    from datetime import datetime
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
    try:
        sekunden = (datetime.strptime(ende, fmt) - datetime.strptime(start, fmt)).total_seconds()
    except ValueError:
        return "unbekannt"
    return f"{sekunden:.1f} s"


def _quellen_tabelle(quellen: list[dict]) -> str:
    zeilen = ["| Datei | Typ | Seiten | Zeichen |", "|---|---|---|---|"]
    for q in quellen:
        zeilen.append(f"| {q['filename']} | {q.get('ext', '?')} | "
                      f"{q.get('pages') if q.get('pages') is not None else '-'} | "
                      f"{_ZAHL(len(q.get('content', '')))} |")
    return "\n".join(zeilen)


def _fakten_tabelle(fakten: dict) -> str:
    zeilen = ["| Datei | Fakten |", "|---|---|"]
    for source_id, liste in fakten.items():
        zeilen.append(f"| {source_id} | {len(liste)} |")
    return "\n".join(zeilen)


def _gliederung_abschnitt(outline: dict | None, fakten: dict) -> str:
    if not outline:
        return "Keine Gliederung gespeichert, der Einzelaufruf hat vermutlich geschrieben."
    gesamt = sum(len(v) for v in fakten.values())
    zugeordnet = sum(len(a.get("fact_ids") or []) for a in outline.get("sections") or [])
    zeilen = [f"Einleitung: {outline.get('intro', '')}", "",
             f"{len(outline.get('sections') or [])} Abschnitte, "
             f"{zugeordnet} von {gesamt} Fakten zugeordnet.", ""]
    for a in outline.get("sections") or []:
        zeilen.append(f"- **{a['title']}** ({len(a.get('fact_ids') or [])} Fakten): "
                      f"{a.get('description') or a.get('scope', '')}")
    return "\n".join(zeilen)


def _aufruf_abschnitt(nummer: int, aufruf: dict) -> str:
    eingabe = aufruf.get("input") or []
    system = next((m.get("content", "") for m in eingabe if m.get("role") == "system"), "")
    nutzer = next((m.get("content", "") for m in eingabe if m.get("role") == "user"), "")
    ausgabe = aufruf.get("output")
    text = ausgabe.get("content") if isinstance(ausgabe, dict) else (ausgabe or "")
    parameter = aufruf.get("modelParameters") or {}
    schema = ((aufruf.get("metadata") or {}).get("response_format") or {}).get("json_schema", {}).get("name")
    kopf = [
        f"## Aufruf {nummer}: {aufruf.get('name', '?')}",
        f"Modell: `{aufruf.get('model', '?')}` · Dauer: {_dauer(aufruf)} · "
        f"Temperatur: {parameter.get('temperature', '-')} · "
        f"Deckel: {parameter.get('max_tokens', '-')} Token" +
        (f" · Schema: `{schema}`" if schema else ""),
        f"Eingabe-Token: {aufruf.get('promptTokens', '?')} · "
        f"Ausgabe-Token: {aufruf.get('completionTokens', '?')}",
        "",
        "**System-Prompt**", "```", system, "```",
        "**Nutzer-Prompt**", "```", nutzer, "```",
        "**Antwort**", "```", text or "(leer)", "```",
    ]
    return "\n".join(kopf)


def render(job_uuid: str) -> str:
    job = db.get_job(job_uuid)
    if not job:
        raise SystemExit(f"Auftrag {job_uuid} nicht gefunden")
    user_id = job["user_id"]

    parameter = _read_json(user_id, job_uuid, "summary_params.json", {})
    quellen = _read_json(user_id, job_uuid, "sources.json", [])
    fakten = _read_json(user_id, job_uuid, "facts.json", {})
    outline = _read_json(user_id, job_uuid, "outline.json", None)
    ergebnis = _read_text(user_id, job_uuid, "summary.md")
    aufrufe = fetch_calls(job_uuid)

    teile = [
        f"# Nachvollzug: Zusammenfassung {job_uuid}",
        "",
        f"Status: {job.get('status')} · Vorlage: `{parameter.get('template_slug', '?')}` · "
        f"Anbieter-Wahl: {parameter.get('provider_id') or 'Standard'}",
        "",
        "## Quellen", "", _quellen_tabelle(quellen), "",
        "## Fakten je Datei", "", _fakten_tabelle(fakten), "",
        "## Gliederung", "", _gliederung_abschnitt(outline, fakten), "",
        f"## KI-Aufrufe ({len(aufrufe)})", "",
    ]
    for i, aufruf in enumerate(aufrufe, start=1):
        teile.append(_aufruf_abschnitt(i, aufruf))
        teile.append("")

    teile.append("## Ergebnis")
    teile.append("")
    if ergebnis:
        teile.append(f"{_ZAHL(len(ergebnis))} Zeichen, beginnt mit:")
        teile.append("```")
        teile.append(ergebnis[:400])
        teile.append("```")
    else:
        teile.append("Noch kein Ergebnis gespeichert.")

    return "\n".join(teile)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_uuid")
    parser.add_argument("--out", default=None, help="Zieldatei, sonst stdout")
    args = parser.parse_args()

    text = render(args.job_uuid)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"geschrieben: {args.out} ({_ZAHL(len(text))} Zeichen)")
    else:
        print(text)


if __name__ == "__main__":
    main()
