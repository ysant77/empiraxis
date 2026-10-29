"""Replay allowlist: a manifest that pins the SHA-256 of every file in a replay folder.

A replay view loads a run only if the run is listed and every file matches its digest.
Unlisted files, missing files, changed files and unsafe names all fail closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

MANIFEST = "MANIFEST.json"
_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class ManifestError(RuntimeError):
    """The replay folder does not match its manifest."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_files(run_dir: Path) -> dict[str, str]:
    return {p.name: _sha256(p) for p in sorted(run_dir.iterdir()) if p.is_file()}


def write_manifest(root: Path, entries: list[dict[str, Any]], *, note: str) -> Path:
    """Record each listed run's file digests. Entries need a ``run`` folder name."""
    runs = []
    for entry in entries:
        name = str(entry["run"])
        if not _SAFE_NAME.match(name):
            raise ManifestError(f"unsafe run name {name!r}")
        runs.append({**entry, "files": _run_files(root / name)})
    path = root / MANIFEST
    path.write_text(json.dumps({"note": note, "runs": runs}, indent=2) + "\n", "utf-8")
    return path


def read_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST
    if not path.is_file():
        raise ManifestError(f"no {MANIFEST} in {root}")
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{MANIFEST} is not valid JSON") from exc
    return data


def verified_run(root: Path, name: str) -> Path:
    """Return the run folder if it is listed and every file matches; raise otherwise."""
    if not _SAFE_NAME.match(name):
        raise ManifestError(f"unsafe run name {name!r}")
    listed = {str(r["run"]): r for r in read_manifest(root).get("runs", [])}
    if name not in listed:
        raise ManifestError(f"run {name!r} is not in the replay allowlist")
    run_dir = root / name
    if not run_dir.is_dir():
        raise ManifestError(f"run {name!r} is missing")
    expected: dict[str, str] = listed[name]["files"]
    found = _run_files(run_dir)
    missing = sorted(set(expected) - set(found))
    extra = sorted(set(found) - set(expected))
    changed = sorted(f for f in set(expected) & set(found) if expected[f] != found[f])
    for label, names in (("missing", missing), ("unlisted", extra), ("changed", changed)):
        if names:
            raise ManifestError(f"run {name!r} has {label} files: {', '.join(names)}")
    return run_dir


def listed_runs(root: Path) -> list[dict[str, Any]]:
    """Manifest entries without their digests, for menus."""
    return [
        {k: v for k, v in r.items() if k != "files"} for r in read_manifest(root).get("runs", [])
    ]
