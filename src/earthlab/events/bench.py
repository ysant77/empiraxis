"""Read development bench output (summary.json, results.jsonl) for display, read-only.

Held-out output is refused: this module never opens a path that names the held-out set,
and it rejects a summary or row whose metadata marks it as held-out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from earthlab.bench.heldout import HELDOUT_PREFIX
from earthlab.events.adapter import HELDOUT_MARK
from earthlab.events.contract import EventV1, Visibility

DEV_LABEL = "development, visible questions"


class HeldoutContentError(RuntimeError):
    """The artifact holds held-out content, which no display view may load."""


@dataclass(frozen=True)
class DevBench:
    path: Path
    label: str
    code_revision: str
    started_at_utc: str
    provider: str | None
    model: str | None
    complete: bool
    rows_expected: int
    rows_written: int
    arms: dict[str, dict[str, Any]]
    blocked_unrun: dict[str, str]
    caveat: str


def _refuse_heldout_path(path: Path) -> None:
    if any(HELDOUT_MARK in part.lower() for part in path.resolve().parts):
        raise HeldoutContentError("held-out paths are never read by the display layer")


def _is_heldout_meta(meta: dict[str, Any]) -> bool:
    scenario_file = meta.get("scenario_file") or {}
    return bool(isinstance(scenario_file, dict) and scenario_file.get("heldout"))


def load_dev_bench(path: Path) -> DevBench:
    """Load one development summary.json; raise if it is held-out or malformed."""
    _refuse_heldout_path(path)
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    arms: dict[str, dict[str, Any]] = data.get("arms", {})
    scenario_ids = {sid for arm in arms.values() for sid in arm.get("per_scenario", {})}
    if _is_heldout_meta(meta) or any(s.startswith(HELDOUT_PREFIX) for s in scenario_ids):
        raise HeldoutContentError("summary is from the held-out set")
    return DevBench(
        path=path,
        label=DEV_LABEL,
        code_revision=str(meta.get("code_revision", "unknown")),
        started_at_utc=str(meta.get("started_at_utc", "unknown")),
        provider=meta.get("provider"),
        model=meta.get("model"),
        complete=bool(data.get("complete")),
        rows_expected=int(data.get("rows_expected", 0)),
        rows_written=int(data.get("rows_written", 0)),
        arms=arms,
        blocked_unrun=dict(data.get("blocked_unrun", {})),
        caveat=str(data.get("caveat", "")),
    )


def find_dev_benches(root: Path) -> list[DevBench]:
    """Every loadable development summary under root, newest first. Skips held-out paths."""
    if not root.is_dir():
        return []
    found: list[DevBench] = []
    for path in root.rglob("summary.json"):
        if any(HELDOUT_MARK in part.lower() for part in path.parts):
            continue
        try:
            found.append(load_dev_bench(path))
        except (HeldoutContentError, json.JSONDecodeError, ValueError, AttributeError):
            continue
    return sorted(found, key=lambda b: b.started_at_utc, reverse=True)


def bench_events(results: Path) -> list[EventV1]:
    """One run_completed event per scored row. A held-out row is internal and unnamed."""
    _refuse_heldout_path(results)
    events: list[EventV1] = []
    lines = results.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        held = _is_heldout_meta(row.get("meta", {})) or str(row["scenario_id"]).startswith(
            HELDOUT_PREFIX
        )
        name = "held-out scenario" if held else str(row["scenario_id"])
        outcome = row.get("outcome", {})
        events.append(
            EventV1(
                event_id=f"{results.parent.name}:row{number}",
                run_id=results.parent.name,
                trace_id=results.parent.name,
                timestamp_utc=str(row.get("meta", {}).get("started_at_utc", "unknown")),
                actor_role="system",
                event_type="run_completed",
                status="completed" if row.get("passed") else "failed",
                message_summary=(
                    f"{name} arm {row['arm']} repeat {row['repeat']}: "
                    f"{'passed' if row.get('passed') else 'not passed'} "
                    f"(run status {outcome.get('status')})"
                ),
                source_trace_ref=f"results.jsonl#line={number}",
                elapsed_ms=round(float(outcome.get("seconds", 0)) * 1000),
                display_visibility=Visibility.INTERNAL if held else Visibility.PUBLIC_DEMO,
            )
        )
    return events
