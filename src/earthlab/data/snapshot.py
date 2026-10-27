"""Load a source manifest and refuse any file whose hash differs from it."""

from __future__ import annotations

import json
from pathlib import Path

from earthlab.contracts import SourceSnapshot
from earthlab.hashing import file_sha256

MANIFEST_NAME = "manifest.json"


class SourceMismatchError(RuntimeError):
    """The file on disk is not the file the manifest pins."""


def load_manifest(data_dir: Path) -> SourceSnapshot:
    raw = json.loads((data_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    fields = set(SourceSnapshot.model_fields)
    return SourceSnapshot.model_validate({k: v for k, v in raw.items() if k in fields})


def open_snapshot(data_dir: Path) -> tuple[SourceSnapshot, Path]:
    """Return the manifest and the verified path of its source file. Fail closed."""
    snapshot = load_manifest(data_dir)
    path = data_dir / snapshot.file
    if not path.is_file():
        raise SourceMismatchError(f"source file missing: {path}")
    actual = file_sha256(path)
    if actual != snapshot.sha256:
        raise SourceMismatchError(
            f"{snapshot.file}: sha256 {actual[:12]}... does not match manifest "
            f"{snapshot.sha256[:12]}..."
        )
    return snapshot, path
