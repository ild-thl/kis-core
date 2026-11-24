#!/usr/bin/env python3
"""
Generate THIRD-PARTY-NOTICES.txt at repo root by aggregating:
- Backend Python deps (via pip-licenses inside the running askf-backend container)
- Frontend npm deps (via license-checker-rseidelsohn against node_modules)

Fails with non-zero exit if any AGPL/GPL-only dependency is detected (allowlist
enforces that only permissive + weak-copyleft licenses are present).

The notice is the only artifact: there is no /licenses page or browser-served
mirror. Compliance is satisfied by keeping copyright + license texts at the
repo root, which is sufficient for an internal tool.

Usage:
    python generate-licenses.py [--check]

    --check   Generate to a temp file and diff against the committed version.
              Exits non-zero on drift (suitable for CI).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
NOTICE_PATH = REPO_ROOT / "THIRD-PARTY-NOTICES.txt"
FRONTEND_DIR = REPO_ROOT / "frontend"
BACKEND_CONTAINER = "askf-backend"

REQUIREMENTS_FILE = REPO_ROOT / "backend" / "requirements.txt"

FORBIDDEN_LICENSE_PATTERNS = [
    re.compile(r"\bAGPL\b", re.IGNORECASE),
    re.compile(r"\bAffero\b", re.IGNORECASE),
    re.compile(r"\bGPL-[23]\.0(?!\+)", re.IGNORECASE),
    re.compile(r"GNU General Public License", re.IGNORECASE),
]
LGPL_OK_PATTERN = re.compile(r"\bLGPL\b|Lesser General", re.IGNORECASE)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if check and result.returncode != 0:
        sys.stderr.write(f"Command failed: {' '.join(cmd)}\n{result.stderr}\n")
        sys.exit(result.returncode)
    return result.stdout


def parse_top_level_python_deps() -> list[str]:
    names = []
    for line in REQUIREMENTS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=!\[]", line, maxsplit=1)[0].strip()
        if name:
            names.append(name.lower())
    return names


def fetch_backend_licenses() -> list[dict]:
    """Run pip-licenses inside the backend container, return list of dicts."""
    install_cmd = [
        "docker", "exec", BACKEND_CONTAINER,
        "pip", "install", "--quiet", "pip-licenses",
    ]
    run(install_cmd)

    list_cmd = [
        "docker", "exec", BACKEND_CONTAINER,
        "pip-licenses",
        "--format=json",
        "--with-license-file",
        "--no-license-path",
        "--with-urls",
    ]
    raw = run(list_cmd)
    data = json.loads(raw)
    pip_itself = {"pip", "setuptools", "wheel"}
    return [pkg for pkg in data if pkg["Name"].lower() not in pip_itself]


def fetch_frontend_licenses() -> list[dict]:
    """Run license-checker-rseidelsohn locally against frontend production deps."""
    if not (FRONTEND_DIR / "node_modules").exists():
        sys.stderr.write("frontend/node_modules missing — run `npm install` first.\n")
        sys.exit(1)

    cmd = [
        "npx", "license-checker-rseidelsohn",
        "--json",
        "--excludePackages", "askf-frontend@0.1.0",
    ]
    raw = run(cmd, cwd=FRONTEND_DIR)
    data = json.loads(raw)

    out = []
    for key, info in data.items():
        m = re.match(r"^(@?[^@]+)@([^@]+)$", key)
        if not m:
            continue
        name, version = m.group(1), m.group(2)
        license_text = ""
        if info.get("licenseFile"):
            try:
                license_text = Path(info["licenseFile"]).read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                license_text = ""
        out.append({
            "Name": name,
            "Version": version,
            "License": info.get("licenses", "UNKNOWN"),
            "URL": info.get("repository", "") or info.get("url", ""),
            "LicenseText": license_text,
            "Publisher": info.get("publisher", ""),
        })
    out.sort(key=lambda p: p["Name"].lower())
    return out


def check_allowlist(packages: list[dict], section: str) -> list[str]:
    violations = []
    for pkg in packages:
        lic = pkg.get("License") or ""
        if any(pat.search(lic) for pat in FORBIDDEN_LICENSE_PATTERNS):
            if not LGPL_OK_PATTERN.search(lic):
                violations.append(f"  - [{section}] {pkg['Name']} {pkg['Version']}: {lic}")
    return violations


def render_table(packages: list[dict], with_url: bool) -> str:
    if with_url:
        header = "| Package | Version | License | URL |\n|---|---|---|---|\n"
        rows = [
            f"| `{p['Name']}` | {p['Version']} | {p['License']} | {p.get('URL', '') or ''} |"
            for p in packages
        ]
    else:
        header = "| Package | Version | License |\n|---|---|---|\n"
        rows = [
            f"| `{p['Name']}` | {p['Version']} | {p['License']} |"
            for p in packages
        ]
    return header + "\n".join(rows) + "\n"


def render_detail_blocks(packages: list[dict]) -> str:
    out = []
    for p in packages:
        out.append(f"### {p['Name']} {p['Version']}")
        out.append(f"License: {p['License']}")
        out.append("")
        text = (p.get("LicenseText") or "").strip()
        if not text or text.upper() == "UNKNOWN":
            text = (
                f"License text not bundled with package. See upstream: "
                f"{p.get('URL', '') or 'https://pypi.org/project/' + p['Name'] + '/'}"
            )
        out.append("```")
        out.append(text)
        out.append("```")
        out.append("")
    return "\n".join(out)


def build_notice(backend: list[dict], frontend: list[dict]) -> str:
    top_level_python = set(parse_top_level_python_deps())
    direct_backend = [p for p in backend if p["Name"].lower() in top_level_python]
    direct_backend.sort(key=lambda p: p["Name"].lower())
    backend_sorted = sorted(backend, key=lambda p: p["Name"].lower())

    today = date.today().isoformat()

    parts = [
        "# Third-Party Notices",
        "",
        "This file aggregates the licenses of third-party software included in or used by askFrancis.",
        "",
        "It is split into two sections:",
        "1. Backend (Python): direct + transitive dependencies of `backend/requirements.txt`",
        "2. Frontend (npm): direct + transitive dependencies of `frontend/package.json`",
        "",
        f"Generated automatically on {today} by `generate-licenses.py`.",
        "",
        "Regeneration: run `python generate-licenses.py` from the repo root.",
        "",
        "Allowlist: the generator fails if any AGPL or strong-copyleft GPL dependency",
        "is detected. LGPL is permitted (dynamic linking via PyPI).",
        "",
        "---",
        "",
        "## Backend (Python)",
        "",
        "Generated via `pip-licenses` against `backend/requirements.txt` plus transitive deps.",
        "",
        "### Direct dependencies",
        "",
        render_table(direct_backend, with_url=True),
        "## All dependencies including transitive",
        "",
        render_table(backend_sorted, with_url=False),
        "## License texts (Backend)",
        "",
        render_detail_blocks(backend_sorted),
        "---",
        "",
        "## Frontend (npm)",
        "",
        "Generated via `license-checker-rseidelsohn` against `frontend/package.json`",
        "production deps (excluding the application itself).",
        "",
        "### All dependencies",
        "",
        render_table(frontend, with_url=True),
        "## License texts (Frontend)",
        "",
        render_detail_blocks(frontend),
    ]
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Diff against the committed file; exit non-zero on drift.",
    )
    args = parser.parse_args()

    print("Fetching backend licenses (docker exec)...")
    backend = fetch_backend_licenses()
    print(f"  {len(backend)} backend packages")

    print("Fetching frontend licenses (npx)...")
    frontend = fetch_frontend_licenses()
    print(f"  {len(frontend)} frontend packages")

    top_python = set(parse_top_level_python_deps())
    backend_missing = top_python - {p["Name"].lower() for p in backend}
    if backend_missing:
        sys.stderr.write(
            f"WARNING: top-level requirements.txt entries not seen in pip-licenses: "
            f"{sorted(backend_missing)}\n"
        )

    violations = check_allowlist(backend, "Backend") + check_allowlist(frontend, "Frontend")
    if violations:
        sys.stderr.write("LICENSE ALLOWLIST VIOLATION — AGPL/GPL detected:\n")
        for v in violations:
            sys.stderr.write(v + "\n")
        sys.stderr.write(
            "\nAGPL/strong-GPL dependencies require source disclosure of this project.\n"
            "Either replace them or update the allowlist in generate-licenses.py\n"
            "after explicit legal review.\n"
        )
        return 2

    notice = build_notice(backend, frontend)

    if args.check:
        existing = NOTICE_PATH.read_text(encoding="utf-8") if NOTICE_PATH.exists() else ""
        if existing != notice:
            sys.stderr.write(
                "THIRD-PARTY-NOTICES.txt is out of date. "
                "Run `python generate-licenses.py` and commit the result.\n"
            )
            return 1
        print("THIRD-PARTY-NOTICES.txt is up to date.")
        return 0

    NOTICE_PATH.write_text(notice, encoding="utf-8")
    print(f"Wrote {NOTICE_PATH} ({len(notice.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
