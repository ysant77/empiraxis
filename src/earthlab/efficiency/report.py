"""Aggregate run profiles into per-arm summaries. Descriptive only: no test, no claim."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from statistics import median
from typing import Any

from earthlab.efficiency.models import MODEL_ROLES, Anomaly, ModelRole, RunProfile

UNCONTROLLED_FACTORS: tuple[str, ...] = (
    "Run order: arms ran in sequence inside a stage, so thermal state, memory pressure and "
    "operating-system cache differ by position. One run per cell cannot separate order "
    "from arm.",
    "Guard warm-up: the first run of a session loaded the safety guard model inside the run. "
    "Those runs carry load time that later runs do not.",
    "Hardware contention: other programs shared the machine. Only system wired memory and "
    "swap were sampled, and on some runs not at all. Process memory does not show model memory.",
    "Code revision: stages ran at different source commits. Prompt or routing changes between "
    "commits are mixed into any arm comparison.",
    "Sampling: server defaults with a random seed. Each cell has one to three runs.",
    "Energy and billed cost: not metered. Local compute is wall time of model calls only.",
)


def _med(values: Iterable[float | int | None]) -> float | None:
    known = [v for v in values if v is not None]
    return float(median(known)) if known else None


def _role_field(
    runs: list[RunProfile], role: ModelRole, pick: Callable[[Any], float | int | None]
) -> dict[str, float | int | None]:
    values = [pick(u) for r in runs if (u := r.usage(role)) is not None]
    known = [v for v in values if v is not None]
    return {"median": _med(known), "runs_with_value": len(known), "runs_with_role": len(values)}


def _share(run: RunProfile, picks: tuple[ModelRole, ...]) -> float | None:
    """Share of model tokens spent in the given roles; None unless every call has usage."""
    if not run.roles or any(u.calls_with_usage != u.model_calls for u in run.roles):
        return None
    total = sum((u.prompt_tokens or 0) + (u.completion_tokens or 0) for u in run.roles)
    part = sum(
        (u.prompt_tokens or 0) + (u.completion_tokens or 0) for u in run.roles if u.role in picks
    )
    return part / total if total else None


def _role_table(complete: list[RunProfile]) -> dict[str, Any]:
    return {
        role: {
            "model_calls": _role_field(complete, role, lambda u: u.model_calls),
            "prompt_tokens": _role_field(complete, role, lambda u: u.prompt_tokens),
            "completion_tokens": _role_field(complete, role, lambda u: u.completion_tokens),
            "wall_seconds": _role_field(complete, role, lambda u: u.wall_seconds),
        }
        for role in MODEL_ROLES
        if any(r.usage(role) for r in complete)
    }


def _overhead(complete: list[RunProfile]) -> dict[str, float | None]:
    groups: dict[str, tuple[ModelRole, ...]] = {
        "pm_and_orchestrator_token_share_median": ("product_manager", "orchestrator"),
        "pm_token_share_median": ("product_manager",),
        "orchestrator_token_share_median": ("orchestrator",),
        "engineer_token_share_median": ("geospatial_engineer",),
    }
    return {name: _med(_share(r, picks) for r in complete) for name, picks in groups.items()}


def summarize_group(runs: list[RunProfile]) -> dict[str, Any]:
    complete = [r for r in runs if r.artifacts == "complete"]
    decided = [r for r in complete if r.goal_satisfied is not None]
    billed = all(r.cost.billed_provider_cost_usd is None for r in runs)
    return {
        "runs": len(runs),
        "runs_with_artifacts": len(complete),
        "goal_satisfied": f"{sum(bool(r.goal_satisfied) for r in decided)}/{len(decided)}",
        "statuses": dict(Counter(r.status for r in complete)),
        "abstained": sum(bool(r.abstained) for r in complete),
        "failed": sum(bool(r.failed) for r in complete),
        "answer_revisions_median": _med(r.answer_revisions for r in complete),
        "manifest_wall_seconds_median": _med(r.manifest_wall_seconds for r in runs),
        "local_model_wall_seconds_median": _med(r.cost.local_model_wall_seconds for r in complete),
        "billed_provider_cost_usd": "not measured" if billed else "see runs",
        "roles": _role_table(complete),
        "stage_overhead": _overhead(complete),
    }


def observed_conditions(runs: list[RunProfile]) -> dict[str, Any]:
    order: dict[str, list[str]] = defaultdict(list)
    for r in sorted(runs, key=lambda x: x.started_utc):
        order[r.stage].append(f"{r.arm}:{r.scenario_id}")
    return {
        "source_commits": dict(Counter(r.source_commit for r in runs)),
        "guard_cold_start_runs": [
            f"{r.stage}/{r.scenario_id}/{r.arm}" for r in runs if r.guard_loaded_at_start is False
        ],
        "runs_with_memory_sample": sum(r.system_wired_peak_mb is not None for r in runs),
        "runs_without_memory_sample": sum(r.system_wired_peak_mb is None for r in runs),
        "start_order_by_stage": dict(order),
    }


def summarize(runs: list[RunProfile], anomalies: list[Anomaly]) -> dict[str, Any]:
    by_arm: dict[str, list[RunProfile]] = defaultdict(list)
    by_cell: dict[str, list[RunProfile]] = defaultdict(list)
    for r in runs:
        by_arm[r.arm].append(r)
        by_cell[f"{r.arm}/{r.scenario_id}"].append(r)
    return {
        "manifest_rows": len(runs),
        "rows_with_complete_artifacts": sum(r.artifacts == "complete" for r in runs),
        "anomalies": [a.model_dump() for a in anomalies],
        "by_arm": {k: summarize_group(v) for k, v in sorted(by_arm.items())},
        "by_arm_and_scenario": {k: summarize_group(v) for k, v in sorted(by_cell.items())},
        "observed_conditions": observed_conditions(runs),
        "uncontrolled_factors": list(UNCONTROLLED_FACTORS),
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "missing"
    return f"{value:.0f}" if isinstance(value, float) else str(value)


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Run profile (descriptive; no claim of saving)",
        "",
        f"Manifest rows: {summary['manifest_rows']}. "
        f"Rows with complete artifacts: {summary['rows_with_complete_artifacts']}.",
        "",
    ]
    lines += [f"- Anomaly `{a['kind']}`: {a['detail']}" for a in summary["anomalies"]]
    lines += ["", "| Arm | Runs | Goal | Role | Calls | Prompt tok | Completion tok | Wall s |"]
    lines += ["|---|---|---|---|---|---|---|---|"]
    for arm, g in summary["by_arm"].items():
        for role, f in g["roles"].items():
            lines.append(
                f"| {arm} | {g['runs_with_artifacts']}/{g['runs']} | {g['goal_satisfied']} "
                f"| {role} | {_fmt(f['model_calls']['median'])} "
                f"| {_fmt(f['prompt_tokens']['median'])} "
                f"| {_fmt(f['completion_tokens']['median'])} "
                f"| {_fmt(f['wall_seconds']['median'])} |"
            )
    lines += [
        "",
        "Values are medians over runs that recorded the field; `missing` is not zero.",
        "",
    ]
    lines += ["## Uncontrolled factors", ""]
    lines += [f"- {text}" for text in summary["uncontrolled_factors"]]
    return "\n".join(lines) + "\n"
