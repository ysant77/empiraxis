"""A read-only view of one recorded PM -> engineer workflow run, built from its trace.

The trace hash chain is verified first. Calls, tokens, latency and served models are
counted from the trace itself; cost and budget come from result.json. A value the record
does not hold is None ("unknown"), never zero. Raw prompts and model reasoning are never
read into the view.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from earthlab.trace import RunTrace

_BINDING_KEYS = {
    "pm": "product_manager",
    "orchestrator": "orchestrator",
    "engineer": "geospatial_engineer",
}
ROLE_NAMES = {
    "product_manager": "Product manager (model)",
    "orchestrator": "Model orchestrator (separate topology)",
    "geospatial_engineer": "Geospatial engineer (Muse investigator, plan-reviewed)",
}


@dataclass
class RoleStats:
    model_calls: int = 0
    failed_calls: int = 0
    prompt_tokens: int | None = 0
    completion_tokens: int | None = 0
    latency_s: float | None = 0.0
    served_models: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class WorkflowView:
    run_id: str
    topology: str
    provenance: str  # "live", "synthetic" or "unknown"
    status: str
    stages: list[dict[str, Any]]
    roles: list[dict[str, Any]]
    retries: list[dict[str, Any]]
    budget: dict[str, Any]
    findings: list[str]
    limitations: list[str]


def _plus(total: Any, value: Any) -> Any:
    return None if total is None or value is None else total + value


def _provenance(kinds: dict[str, str] | None) -> str:
    if not kinds:
        return "unknown"
    return "live" if all(k == "live_http" for k in kinds.values()) else "synthetic"


def _stage(entry: dict[str, Any], role: str | None) -> dict[str, Any] | None:
    """One row for a workflow step, or None for an entry the stage table does not show."""
    d, event = entry["data"], entry["event"]
    valid = "accepted" if d.get("valid") else "rejected"
    issues = "; ".join(d.get("issues", []))
    rows = {
        "brief_reviewed": ("PM brief", "product_manager",
                           valid,
                           f"route {d.get('route')}" if d.get("valid") else issues),
        "decision_reviewed": ("Orchestrator decision", "orchestrator",
                              valid,
                              str(d.get("decision")) if d.get("valid") else issues),
        "task_handoff": ("Engineer assignment", "system", "created",
                         f"case {(d.get('task') or {}).get('case_id')}, "
                         f"{len((d.get('task') or {}).get('allowed_tool_names', []))} tools"),
        "plan_reviewed": ("Plan review (deterministic critic)", "scientific_critic",
                          str(d.get("verdict")), f"revision {d.get('plan_revision')}"),
        "tool_result": ("Tool call", role or "orchestrator", str(d.get("outcome")),
                        str(d.get("name"))),
        "tool_skipped": ("Tool call refused", role or "orchestrator", "refused",
                         f"{d.get('name')}: {d.get('reason')}"),
        "result_delivered": ("Verified result to PM", "system",
                             str((d.get("reply") or {}).get("status")),
                             ", ".join((d.get("reply") or {}).get("supported_finding_ids", []))
                             or "no verified finding"),
        "pm_report": ("PM report", "product_manager",
                      "passed" if d.get("passed") else "not shown",
                      f"shown: {d.get('source')}"),
        "finish": ("Run finished", "system", str(d.get("status")), str(d.get("reason"))),
    }  # fmt: skip
    if event not in rows or (event == "finish" and not d.get("workflow")):
        return None
    stage, actor, status, detail = rows[event]
    return {"seq": entry["seq"], "stage": stage, "role": actor, "status": status,
            "detail": detail[:200]}  # fmt: skip


def _count(stats: dict[str, RoleStats], role: str, entry: dict[str, Any]) -> None:
    s = stats.setdefault(role, RoleStats())
    d = entry["data"]
    s.model_calls += 1
    if entry["event"] == "model_error":
        s.failed_calls += 1
        ms = d.get("elapsed_ms")
        s.latency_s = _plus(s.latency_s, None if ms is None else ms / 1000)
        return
    usage = d.get("usage") or {}
    s.prompt_tokens = _plus(s.prompt_tokens, usage.get("prompt_tokens"))
    s.completion_tokens = _plus(s.completion_tokens, usage.get("completion_tokens"))
    s.latency_s = _plus(s.latency_s, d.get("wall_seconds"))
    if d.get("served_model"):
        s.served_models.add(str(d["served_model"]))


def _role_rows(
    stats: dict[str, RoleStats], bindings: dict[str, Any], usage: dict[str, Any]
) -> list[dict[str, Any]]:
    rows = []
    for key, role in _BINDING_KEYS.items():
        bound = bindings.get(key)
        if bound is None and role not in stats:
            continue
        s, cost = stats.get(role, RoleStats()), (usage.get(role) or {}).get("cost_usd")
        configured = (bound or {}).get("model_id")
        served = sorted(s.served_models)
        rows.append({
            "role": ROLE_NAMES[role], "provider": (bound or {}).get("provider_id"),
            "configured model": configured, "served model": ", ".join(served) or None,
            "served matches": (all(m == configured for m in served) if served else None),
            "status": (bound or {}).get("implementation"), "calls": s.model_calls,
            "failed calls": s.failed_calls, "prompt tokens": s.prompt_tokens,
            "completion tokens": s.completion_tokens,
            "latency s": None if s.latency_s is None else round(s.latency_s, 3),
            "cost usd": cost,
        })  # fmt: skip
    return rows


def load_workflow(run_dir: Path) -> WorkflowView | None:
    """The workflow view of a verified run, or None when the run is not a workflow run.

    Raises TraceIntegrityError on a broken chain, like the event adapter.
    """
    trace = RunTrace(run_dir / "trace.jsonl")
    trace.verify()
    entries = list(trace.records())
    start = next((e for e in entries if e["event"] == "workflow_start"), None)
    if start is None:
        return None
    path = run_dir / "result.json"
    result = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    block = result.get("workflow") or {}
    stats: dict[str, RoleStats] = {}
    stages, retries, acting = [], [], None
    for entry in entries:
        event, d = entry["event"], entry["data"]
        if event == "role_invocation":
            acting = d.get("role") if d.get("phase") == "started" else None
        if event in ("model_turn", "model_error"):
            _count(stats, d.get("role") or acting or "orchestrator", entry)
        if event == "model_error" or event == "model_retry_skipped":
            retries.append({
                "seq": entry["seq"], "role": d.get("role") or acting, "event": event,
                "kind": d.get("kind"), "attempt": d.get("attempt"),
                "retrying": d.get("retrying"), "reason": d.get("reason"),
            })  # fmt: skip
        if (row := _stage(entry, acting)) is not None:
            stages.append(row)
    manager = block.get("manager_result") or {}
    return WorkflowView(
        run_id=run_dir.name,
        topology=str(start["data"].get("topology")),
        provenance=_provenance(start["data"].get("client_kinds")),
        status=str(result.get("status")),
        stages=stages,
        roles=_role_rows(stats, start["data"].get("bindings") or {}, block.get("usage") or {}),
        retries=retries,
        budget={
            "limits": start["data"].get("budget"),
            "used": (block.get("usage") or {}).get("total"),
        },
        findings=list(manager.get("verified_finding_refs", [])),
        limitations=list(manager.get("typed_limitations", [])),
    )
