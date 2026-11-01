"""Load recorded runs: a manifest plus one folder per run with result.json and trace.jsonl.

The loader only reads. Role attribution uses the runtime's own `role_invocation` brackets,
then the `role` field on a model turn, then the engineer as the default (the direct arm has
no brackets and one role).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from earthlab.efficiency.models import (
    MODEL_ROLES,
    Anomaly,
    CostRecord,
    ModelRole,
    RoleUsage,
    RunProfile,
)

Json = dict[str, Any]
_ROLE_NAMES: set[str] = set(MODEL_ROLES)


def read_jsonl(path: Path) -> list[Json]:
    rows: list[Json] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def attribute_turns(trace: list[Json]) -> dict[ModelRole, list[Json]]:
    """Group model turns by role."""
    turns: dict[ModelRole, list[Json]] = defaultdict(list)
    active: ModelRole | None = None
    for event in trace:
        data = event.get("data", {})
        if event.get("event") == "role_invocation":
            role = data.get("role")
            if data.get("phase") == "started" and role in _ROLE_NAMES:
                active = role
            elif data.get("phase") == "finished":
                active = None
        elif event.get("event") == "model_turn":
            named = data.get("role")
            role = active or (named if named in _ROLE_NAMES else "geospatial_engineer")
            turns[role].append(data)
    return turns


def _sum_known(values: list[float | int | None]) -> tuple[float | int | None, int]:
    known = [v for v in values if v is not None]
    return (sum(known) if known else None), len(known)


def role_usage(role: ModelRole, turns: list[Json]) -> RoleUsage:
    usages = [t.get("usage") if isinstance(t.get("usage"), dict) else None for t in turns]
    prompt, with_usage = _sum_known([u.get("prompt_tokens") if u else None for u in usages])
    completion, _ = _sum_known([u.get("completion_tokens") if u else None for u in usages])
    wall, with_wall = _sum_known([t.get("wall_seconds") for t in turns])
    return RoleUsage(
        role=role,
        model_calls=len(turns),
        calls_with_usage=with_usage,
        calls_with_wall=with_wall,
        prompt_tokens=None if prompt is None else int(prompt),
        completion_tokens=None if completion is None else int(completion),
        wall_seconds=None if wall is None else round(float(wall), 3),
    )


def _goal(manifest: Json, status: str | None) -> bool | None:
    """Goal check against the manifest's expected outcome, by its leading word."""
    if status is None:
        return None
    expected = str(manifest.get("expected", "")).split(" ", 1)[0]
    return status == expected if expected in {"verified", "abstained"} else None


def _cost(manifest: Json, result: Json | None, roles: tuple[RoleUsage, ...]) -> CostRecord:
    walls = [u.wall_seconds for u in roles if u.wall_seconds is not None]
    note = str(manifest.get("provider_cost_usd", "NOT_MEASURED"))
    estimate = result.get("estimated_cost_usd") if result else None
    return CostRecord(
        local_model_wall_seconds=round(sum(walls), 3) if walls else None,
        billed_provider_cost_usd=None,
        billed_cost_note=note,
        estimated_cost_usd=estimate if isinstance(estimate, int | float) else None,
    )


def _load_files(run_dir: Path) -> tuple[Json | None, list[Json] | None]:
    result_file, trace_file = run_dir / "result.json", run_dir / "trace.jsonl"
    result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else None
    trace = read_jsonl(trace_file) if trace_file.exists() else None
    return result, trace


def profile_run(manifest: Json, runs_dir: Path) -> RunProfile:
    run_id = manifest.get("run_id")
    run_dir = runs_dir / run_id if run_id else None
    result, trace = _load_files(run_dir) if run_dir and run_dir.is_dir() else (None, None)
    artifacts = (
        "no_run_folder"
        if result is None and trace is None and not (run_dir and run_dir.is_dir())
        else "no_trace"
        if trace is None
        else "no_result"
        if result is None
        else "complete"
    )
    turns = attribute_turns(trace or [])
    roles = tuple(role_usage(r, turns[r]) for r in MODEL_ROLES if turns.get(r))
    status = result.get("status") if result else None
    goal = _goal(manifest, status)
    revisions = sum(e.get("event") == "answer_revision" for e in trace) if trace else None
    return RunProfile(
        run_id=run_id,
        stage=manifest["stage"],
        scenario_id=manifest["scenario_id"],
        arm=manifest["arm"],
        started_utc=manifest["started_utc"],
        source_commit=str(manifest.get("source_commit_sha", ""))[:7],
        exit_code=manifest.get("exit_code"),
        manifest_wall_seconds=manifest.get("wall_seconds"),
        artifacts=artifacts,
        status=status,
        expected=str(manifest.get("expected", "")),
        goal_satisfied=goal,
        abstained=None if status is None else status == "abstained",
        failed=None if status is None else status not in {"verified", "abstained"},
        answer_revisions=revisions,
        guard_loaded_at_start=manifest.get("guard_loaded_at_start"),
        system_wired_peak_mb=manifest.get("system_wired_peak_mb"),
        swap_used_peak_mb=manifest.get("swap_used_peak_mb"),
        roles=roles,
        cost=_cost(manifest, result, roles),
    )


def load_runs(runs_dir: Path) -> tuple[list[RunProfile], list[Anomaly]]:
    """Profile every manifest row and report rows or folders that do not join."""
    rows = read_jsonl(runs_dir / "manifest.jsonl")
    profiles = [profile_run(row, runs_dir) for row in rows]
    anomalies = [
        Anomaly(
            kind="manifest_row_without_artifacts",
            detail=f"{p.stage}/{p.scenario_id}/{p.arm} started {p.started_utc}, run_id {p.run_id}",
        )
        for p in profiles
        if p.artifacts != "complete"
    ]
    listed = {p.run_id for p in profiles}
    for folder in sorted(runs_dir.iterdir()):
        if folder.is_dir() and (folder / "trace.jsonl").exists() and folder.name not in listed:
            anomalies.append(Anomaly(kind="run_folder_not_in_manifest", detail=folder.name))
    return profiles, anomalies
