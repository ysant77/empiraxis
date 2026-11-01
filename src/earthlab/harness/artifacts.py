"""Immutable, content-addressed records of one run. A changed file is refused on read."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from earthlab.digest import file_digest
from earthlab.trace import RunTrace


class MissingArtifact(ValueError):
    """A referenced artifact is absent or its bytes have changed."""


class ArtifactStore:
    def __init__(self, run_dir: Path, trace: RunTrace):
        self.folder = run_dir / "artifacts"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.trace = trace

    def put(self, name: str, record: BaseModel, task_id: str) -> str:
        """Write once. The same name cannot be written twice in a run."""
        text = json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True)
        path = self.folder / f"{name}.json"
        with path.open("x", encoding="utf-8") as out:
            out.write(text)
        digest = file_digest(path)
        self.trace.append("artifact_stored", "runtime", name=name, sha256=digest, task_id=task_id)
        return digest

    def get(self, name: str, sha256: str) -> str:
        path = self.folder / f"{name}.json"
        if not path.is_file():
            raise MissingArtifact(f"{name} is missing")
        if file_digest(path) != sha256:
            raise MissingArtifact(f"{name} has changed")
        return path.read_text(encoding="utf-8")


def verify_file(path: Path, sha256: str) -> None:
    """Refuse a missing or stale model or prediction file."""
    if not path.is_file():
        raise MissingArtifact(f"{path.name} is missing")
    if file_digest(path) != sha256:
        raise MissingArtifact(f"{path.name} does not match its recorded digest")
