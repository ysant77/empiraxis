"""The sealed held-out ScienceBench set. The question file stays outside the repo; the repo
holds only a lock with its SHA-256. A held-out file whose hash does not match the lock is
refused, and every bench run records the hash of the scenario file it used.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from earthlab.bench.scenarios import Scenario
from earthlab.contracts import Strict
from earthlab.digest import file_digest

HELDOUT_PREFIX = "HO-"
DEV_NOTE = "Visible development fixtures; not a blind holdout."


class HeldoutError(ValueError):
    """The scenario file is held-out but has no lock, or does not match it."""


class HeldoutLock(Strict):
    set_id: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    questions: int = Field(ge=1)
    frozen_at: date
    blindness: str = Field(min_length=20)


def load_lock(path: Path) -> HeldoutLock:
    return HeldoutLock.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _check_locked_set(path: Path, scenarios: list[Scenario]) -> None:
    """A locked set holds only HO- scenarios, and all of them run."""
    if not all(s.id.startswith(HELDOUT_PREFIX) for s in scenarios):
        raise HeldoutError(f"{path.name}: a locked set holds only HO- scenarios")
    idle = [s.id for s in scenarios if s.status != "ready"]
    if idle:
        raise HeldoutError(f"{path.name}: held-out scenarios not ready: {', '.join(idle)}")


def scenario_file_record(
    path: Path, scenarios: list[Scenario], lock: HeldoutLock | None
) -> dict[str, Any]:
    """Hash the scenario file; for a held-out file, require a matching lock."""
    digest = file_digest(path)
    heldout = any(s.id.startswith(HELDOUT_PREFIX) for s in scenarios)
    if heldout and lock is None:
        raise HeldoutError(f"{path.name}: held-out scenarios need --heldout-lock")
    if lock is not None:
        if digest != lock.sha256:
            raise HeldoutError(f"{path.name}: SHA-256 {digest} does not match the lock")
        if not heldout or len(scenarios) != lock.questions:
            raise HeldoutError(f"{path.name}: expected {lock.questions} held-out scenarios")
        _check_locked_set(path, scenarios)
    return {
        "name": path.name,
        "sha256": digest,
        "heldout": heldout,
        "set_id": lock.set_id if lock else None,
        "note": f"Held-out set {lock.set_id}. {lock.blindness}" if lock else DEV_NOTE,
    }
