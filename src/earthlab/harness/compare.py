"""The comparison report: fixed pipeline, one agent, and the team, on the same tasks.

Numbers come only from saved run records. Three dimensions stay apart: scientific result,
engineering cost and agent cost. A value no run recorded prints as not measured, never zero.
Energy and hardware cost are not metered, so local cost is reported as time and memory only.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

REPORT_VERSION = 1
NOT_MEASURED = "not measured"
ARMS = ("fixed", "single", "team")


def load_runs(manifest: Path) -> list[dict[str, Any]]:
    """Every row with a saved record. A row without one is kept as a failed run."""
    out = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if "scenario" not in row:
            continue
        path = Path(row["run"]) / "result.json" if row.get("run") else None
        record = (
            json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else {}
        )  # fmt: skip
        out.append(
            {
                "scenario": row["scenario"],
                "arm": row.get("arm_id", row["arm"]),
                "variant": row.get("prompt_variant"),
                "models": row.get("models"),
                "ranked": row.get("ranked", True),
                "record": record,
            }
        )
    return out


def _spread(values: list[float]) -> str:
    if not values:
        return NOT_MEASURED
    return f"{median(values):g} ({min(values):g} to {max(values):g})"


def _numbers(rows: list[dict[str, Any]], key: str) -> list[float]:
    found = [r["record"].get("usage", {}).get(key) for r in rows]
    return [float(v) for v in found if isinstance(v, int | float)]


def _billed(rows: list[dict[str, Any]]) -> float | str:
    """A sum only when every run holds a recorded bill. Usage records are not a bill."""
    bills = _numbers(rows, "billed_usd")
    return round(sum(bills), 6) if rows and len(bills) == len(rows) else NOT_MEASURED


def _picked(record: dict[str, Any]) -> str:
    rec = record.get("recommendation") or {}
    return f"{rec.get('outcome', record.get('status', 'none'))} {rec.get('model_id') or ''}".strip()


def agrees_with_code(record: dict[str, Any]) -> bool | None:
    """Did the recommendation match what code alone concluded? None when there is no result."""
    rec = record.get("recommendation")
    if rec is None or "code_outcome" not in record:
        return None
    return bool(rec["outcome"] == record["code_outcome"])


def _variants(rows: list[dict[str, Any]]) -> str:
    found = sorted({str(r["variant"]) for r in rows if r.get("variant")})
    return ", ".join(found) or NOT_MEASURED


def _models(rows: list[dict[str, Any]]) -> str:
    """Role to provider, as the manifest recorded it. Blank for an arm with no model."""
    found = sorted({json.dumps(r["models"], sort_keys=True) for r in rows if r.get("models")})
    return "; ".join(found) or "none"


def cell(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """One scenario and one arm, over its repeats."""
    records = [r["record"] for r in rows]
    accepted = sum(bool(a) and all(a.values()) for a in (r.get("acceptance") for r in records))
    return {
        "runs": len(rows),
        "prompt_variant": _variants(rows),
        "models": _models(rows),
        "ranked": "yes" if all(r.get("ranked", True) for r in rows) else "no: Lead gate waived",
        "reached_decision_gate": sum(r.get("state") == "forwarded" for r in records),
        "ended_in_refusal_or_abstention": sum(
            r.get("state") in ("refused", "abstained") for r in records
        ),
        "failed": sum(r.get("state") == "failed" or not r for r in records),
        "acceptance_passed": accepted,
        "outcomes": dict(Counter(_picked(r) for r in records)),
        "strategies": dict(Counter(str(r.get("strategy")) for r in records)),
        "plan_changed_by_model": sum(bool(r.get("model_changed_the_plan")) for r in records),
        "agrees_with_code_rule": sum(agrees_with_code(r) is True for r in records),
        "wall_seconds": _spread(_numbers(rows, "wall_seconds")),
        "inference_seconds": _spread(_numbers(rows, "inference_seconds")),
        "training_seconds": _spread(_numbers(rows, "training_seconds")),
        "peak_training_rss_mb": _spread(_numbers(rows, "peak_training_rss_mb")),
        "model_calls": _spread(_numbers(rows, "model_calls")),
        "prompt_tokens": _spread(_numbers(rows, "prompt_tokens")),
        "completion_tokens": _spread(_numbers(rows, "completion_tokens")),
        "retries": sum(_numbers(rows, "retries")),
        "provider_faults": sum(_numbers(rows, "provider_faults")),
        "rejected_tool_calls": sum(_numbers(rows, "rejected_tool_calls")),
        "human_interventions": sum(_numbers(rows, "human_interventions")),
        "energy": NOT_MEASURED,
        "billed_usd": _billed(rows),
    }


def build(runs: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios = sorted({r["scenario"] for r in runs})
    labels = [a for a in dict.fromkeys(r["arm"] for r in runs)]
    labels.sort(key=lambda a: ARMS.index(a) if a in ARMS else len(ARMS))
    table = {
        name: {
            arm: cell(rows)
            for arm in labels
            if (rows := [r for r in runs if r["scenario"] == name and r["arm"] == arm])
        }
        for name in scenarios
    }
    return {"version": REPORT_VERSION, "runs": len(runs), "scenarios": table}


SECTIONS = (
    ("Arm", ("prompt_variant", "models", "ranked")),
    ("Scientific result", ("runs", "reached_decision_gate", "ended_in_refusal_or_abstention",
                           "failed", "acceptance_passed", "outcomes", "strategies",
                           "agrees_with_code_rule")),
    ("Engineering cost", ("wall_seconds", "training_seconds", "peak_training_rss_mb", "energy")),
    ("Agent cost", ("model_calls", "prompt_tokens", "completion_tokens", "inference_seconds",
                    "plan_changed_by_model", "retries", "provider_faults",
                    "rejected_tool_calls", "human_interventions", "billed_usd")),
)  # fmt: skip


def markdown(report: dict[str, Any]) -> str:
    lines = [f"# Harness comparison, version {report['version']}", ""]
    lines += [
        f"{report['runs']} saved runs. Median (low to high). Validation only.",
        "",
    ]
    for name, arms in report["scenarios"].items():
        lines += [f"## {name}", ""]
        heads = list(arms)
        for title, keys in SECTIONS:
            lines += [f"### {title}", "", "| Measure | " + " | ".join(heads) + " |"]
            lines.append("|---|" + "---|" * len(heads))
            for key in keys:
                values = " | ".join(str(arms[a][key]) for a in heads)
                lines.append(f"| {key.replace('_', ' ')} | {values} |")
            lines.append("")
    return "\n".join(lines)
