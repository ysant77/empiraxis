"""E2 bench metrics: model calls read from each run's verified trace, the hashes of the
files that define a run, and the per-arm summary. Bench mode has no human step, so every
row records an empty intervention list; that is not a measure of real-world human effort.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from earthlab.bench.scenarios import Outcome, Scenario, ScenarioScore
from earthlab.digest import file_digest
from earthlab.trace import RunTrace

# Files whose change can change a score. A protocol freeze pins these hashes.
CONFIG_FILES = (
    "src/earthlab/agent/prompts.py",
    "src/earthlab/agent/loop.py",
    "src/earthlab/bench/dispatcher.py",
    "src/earthlab/bench/runner.py",
    "src/earthlab/bench/scenarios.py",
    "src/earthlab/verify/answer_audit.py",
    "src/earthlab/safety/gate.py",
    "src/earthlab/safety/scope.py",
    "src/earthlab/safety/llama_guard.py",
    "config/providers.yaml",
    "config/ollama/earthlab-guard.Modelfile",
)
CAVEAT = "Counts from a small question set. They do not estimate general performance."
INTERVENTIONS_NOTE = (
    "Bench mode has no human approval or edit step; each row records an empty list. "
    "This count is not a measure of real-world human effort."
)
COST_NOTE = (
    "billed_inference_usd is the provider price times the token counts. It excludes local "
    "hardware, energy, the safety model and developer time, so it is not the operating cost."
)

Row = tuple[Scenario, ScenarioScore, Outcome]


def trace_counts(run_dir: Path) -> dict[str, int]:
    """Counts read from the hash-chained run trace, not from the loop's own counters.

    The whole chain is verified first; a broken chain raises TraceIntegrityError, which the
    bench records as an error row. A rejected tool call is one the budget skipped or the
    registry did not execute.
    """
    trace = RunTrace(run_dir / "trace.jsonl")
    trace.verify()
    entries = list(trace.records())
    events = [e["event"] for e in entries]
    errors = events.count("model_error")
    not_run = sum(
        e["event"] == "tool_result" and e["data"].get("outcome") != "executed" for e in entries
    )
    return {
        "model_calls": events.count("model_turn") + errors,
        "provider_errors": errors,
        "rejected_tool_calls": events.count("tool_skipped") + not_run,
    }


def config_hashes(repo: Path) -> dict[str, str]:
    files = [repo / name for name in CONFIG_FILES]
    files += sorted((repo / "config" / "methods").glob("*.yaml"))
    return {str(p.relative_to(repo)): file_digest(p) for p in files if p.is_file()}


def _total_cost(outcomes: list[Outcome]) -> float | None:
    """None when any row has an unknown cost: an unknown cost is never counted as zero."""
    if any(o.cost_usd is None for o in outcomes):
        return None
    return round(sum(o.cost_usd or 0.0 for o in outcomes), 6)


def _ratios(rows: list[Row], key: Any) -> dict[str, str]:
    groups = sorted({key(r) for r in rows})
    return {
        g: f"{sum(r[1].passed for r in rows if key(r) == g)}/{sum(1 for r in rows if key(r) == g)}"
        for g in groups
    }


def arm_summary(rows: list[Row]) -> dict[str, Any]:
    scores, outcomes = [r[1] for r in rows], [r[2] for r in rows]
    passed = sum(s.passed for s in scores)
    false_verified = sum(s.false_verified for s in scores)
    cost = _total_cost(outcomes)
    return {
        "runs": len(rows),
        "repeats": len({s.repeat for s in scores}),
        "passed": passed,
        "completion": round(passed / len(rows), 3),
        "false_verified": false_verified,
        "gate": "fail" if false_verified else "pass",
        "errors": sum(o.status == "error" for o in outcomes),
        "median_seconds": round(statistics.median(o.seconds for o in outcomes), 1),
        "model_calls": sum(o.model_calls for o in outcomes),
        "provider_errors": sum(o.provider_errors for o in outcomes),
        "tool_calls": sum(o.tool_calls for o in outcomes),
        "rejected_tool_calls": sum(o.rejected_tool_calls for o in outcomes),
        "guard_blocks": sum(o.guard_blocks for o in outcomes),
        "prompt_tokens": sum(o.prompt_tokens for o in outcomes),
        "completion_tokens": sum(o.completion_tokens for o in outcomes),
        "billed_inference_usd": cost,
        "billed_inference_per_pass_usd": (
            round(cost / passed, 6) if cost is not None and passed else None
        ),
        "bench_intervention_records": sum(len(o.interventions) for o in outcomes),
        "by_expected": _ratios(rows, lambda r: r[0].expected),
        "per_scenario": _ratios(rows, lambda r: r[0].id),
    }


def summarize(rows: list[Row], blocked: list[Scenario]) -> dict[str, Any]:
    arms = {
        arm: arm_summary([r for r in rows if r[1].arm == arm]) for arm in {r[1].arm for r in rows}
    }
    return {
        "arms": dict(sorted(arms.items())),
        "blocked_unrun": {s.id: s.blocked_reason for s in blocked},
        "caveat": CAVEAT,
        "cost_note": COST_NOTE,
        "interventions_note": INTERVENTIONS_NOTE,
    }
