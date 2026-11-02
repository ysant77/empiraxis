"""The integrated comparison of deterministic, single-agent and multi-agent execution.

Numbers come only from saved run records and validation rows. Sources stay apart, because they
ran at different commits. A pair exists only where the same scenario ran in the same source. A
missing value prints as not measured. Saved records are read and never changed.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from statistics import median
from typing import Any

from earthlab.harness.compare import NOT_MEASURED, load_runs

SEGMENTATION = "burned-area-segmentation"
ORDER = ("adopt", "adopt_limited", "retain_baseline", "abstain", "request_resource")
Replay = Callable[[Path], bool]


def workflow_of(arm: str) -> str:
    if arm in ("F", "fixed"):
        return "deterministic"
    if arm in ("S-M", "single"):
        return "single agent"
    if arm.startswith("S-"):
        return "small-model fallback"
    return "multi-agent"


def verified_goal(scenario: str, record: dict[str, Any], replayed: bool) -> bool:
    """The five rules of benchmark protocol section 4.1, from one saved record."""
    rec, checks = record.get("recommendation") or {}, record.get("acceptance") or {}
    return (
        record.get("status") == "awaiting_human"
        and bool(checks) and all(checks.values())
        and bool(rec) and rec.get("outcome") == record.get("code_outcome")
        and replayed
        and (scenario != SEGMENTATION or rec.get("outcome") == "request_resource")
    )  # fmt: skip


def scored(source: str, manifest: Path, replay: Replay) -> list[dict[str, Any]]:
    out = []
    for row in load_runs(manifest):
        replayed = bool(row["record"]) and bool(row["run"]) and replay(Path(row["run"]))
        out.append({
            **row, "source": source, "workflow": workflow_of(row["arm"]),
            "status": row["record"].get("status", "no record"), "replayed": replayed,
            "vgc": verified_goal(row["scenario"], row["record"], replayed),
        })  # fmt: skip
    return out


def _used(rows: list[dict[str, Any]], key: str) -> list[float]:
    found = [r["record"].get("usage", {}).get(key) for r in rows]
    return [float(v) for v in found if isinstance(v, int | float)]


def _median(values: list[float]) -> float | str:
    return round(median(values), 1) if values else NOT_MEASURED


def _largest(values: list[float]) -> float | str:
    return round(max(values), 1) if values and max(values) > 0 else NOT_MEASURED


def _tokens(rows: list[dict[str, Any]]) -> list[float]:
    prompt, done = _used(rows, "prompt_tokens"), _used(rows, "completion_tokens")
    return [a + b for a, b in zip(prompt, done, strict=True)] if len(prompt) == len(done) else []


def summary_row(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    gated = [r for r in rows if r["status"] == "awaiting_human"]
    return {
        "group": label, "runs": len(rows), "vgc": sum(r["vgc"] for r in rows),
        "safe_stops": sum(r["status"] in ("abstained", "needs_revision") for r in rows),
        "failed": sum(r["status"] in ("failed", "no record") for r in rows),
        "replays_clean": sum(r["replayed"] for r in rows),
        "median_wall_s_reached_gate": _median(_used(gated, "wall_seconds")),
        "total_wall_s": round(sum(_used(rows, "wall_seconds")), 1),
        "median_model_calls": _median(_used(rows, "model_calls")),
        "median_tokens": _median(_tokens(rows)),
        "largest_training_rss_mb": _largest(_used(rows, "peak_training_rss_mb")),
    }  # fmt: skip


def by_arm(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = dict.fromkeys((r["source"], r["workflow"], r["arm"]) for r in runs)
    return [
        {"source": s, "workflow": w} | summary_row(a, [
            r for r in runs if (r["source"], r["workflow"], r["arm"]) == (s, w, a)
        ])
        for s, w, a in labels
    ]  # fmt: skip


def coverage(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Which workflows ran each scenario, in each source. Nothing else is a matched task."""
    keys = sorted({(r["source"], r["scenario"]) for r in runs})
    out = []
    for source, scenario in keys:
        rows = [r for r in runs if (r["source"], r["scenario"]) == (source, scenario)]
        ran = Counter(r["workflow"] for r in rows)
        out.append({
            "source": source, "scenario": scenario, **dict(ran),
            "all_three": all(ran[w] for w in ("deterministic", "single agent", "multi-agent")),
        })  # fmt: skip
    return out


def _outcome(record: dict[str, Any]) -> str:
    rec = record.get("recommendation") or {}
    return str(rec.get("outcome") or record.get("status", "no record"))


def matched(runs: list[dict[str, Any]], arms: tuple[str, ...], source: str) -> list[dict[str, Any]]:
    """Scenarios that every named arm ran in one source, with each arm's own numbers."""
    rows = [r for r in runs if r["source"] == source]
    names = sorted({r["scenario"] for r in rows})
    out = []
    for name in names:
        cells = {a: [r for r in rows if r["scenario"] == name and r["arm"] == a] for a in arms}
        if not all(cells.values()):
            continue
        row: dict[str, Any] = {"scenario": name}
        for arm, found in cells.items():
            row[arm] = {
                "outcome": dict(Counter(_outcome(r["record"]) for r in found)),
                "vgc": sum(r["vgc"] for r in found), "runs": len(found),
                "median_wall_s": _median(_used(found, "wall_seconds")),
                "median_model_calls": _median(_used(found, "model_calls")),
                "median_tokens": _median(_tokens(found)),
            }  # fmt: skip
        out.append(row)
    return out


def selection(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each model decision against the code rule, and each stop with its stated reason."""
    out = []
    for r in runs:
        rec, code = r["record"].get("recommendation") or {}, r["record"].get("code_outcome")
        if r["workflow"] == "deterministic":
            continue
        more = rec.get("outcome") in ORDER and code in ORDER and (
            ORDER.index(rec["outcome"]) < ORDER.index(code)
        )  # fmt: skip
        out.append({
            "source": r["source"], "scenario": r["scenario"], "arm": r["arm"],
            "outcome": _outcome(r["record"]), "code_outcome": code or NOT_MEASURED,
            "matches_code": bool(rec) and rec.get("outcome") == code,
            "more_permissive_than_code": more, "changed_plan":
            bool(r["record"].get("model_changed_the_plan")),
            "stop_reason": "" if rec else str(r["record"].get("reason", ""))[:120],
        })  # fmt: skip
    return out
