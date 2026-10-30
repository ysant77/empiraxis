"""Map a recorded run folder (trace.jsonl, result.json) to EventV1 records, read-only.

The adapter verifies the trace hash chain first and fails closed on a missing, empty,
broken or unknown trace. Actor roles come only from what the trace records. The model's
raw text and reasoning are never copied into an event.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from earthlab.events.contract import ActorRole, EventStatus, EventType, EventV1, Visibility
from earthlab.trace import RunTrace

SUBMIT_TOOLS = frozenset({"submit_findings", "submit_area_findings"})
HELDOUT_MARK = "heldout"
_SUMMARY_LIMIT = 240


class TraceMissingError(RuntimeError):
    """The run folder has no trace, or the trace is empty."""


class UnknownEventError(RuntimeError):
    """The trace holds an event or actor that the adapter does not know."""


class ResultMismatchError(RuntimeError):
    """result.json does not agree with the verified trace."""


@dataclass
class _State:
    run_id: str
    trace_id: str
    visibility: Visibility
    heldout: bool
    last_model_event: str | None = None
    agent_role: ActorRole | None = None  # set while a workflow role is running
    events: list[EventV1] = field(default_factory=list)


@dataclass(frozen=True)
class RunEvents:
    run_id: str
    trace_records: int
    trace_head: str
    closed: bool
    heldout: bool
    status: str | None
    events: list[EventV1]


def _agent(state: _State) -> ActorRole:
    """The model role acting now: a workflow role, else the single Muse investigator."""
    return state.agent_role or "orchestrator"


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _SUMMARY_LIMIT else text[: _SUMMARY_LIMIT - 3] + "..."


def _emit(
    state: _State,
    entry: dict[str, Any],
    actor: ActorRole,
    event_type: EventType,
    status: EventStatus,
    summary: str,
    **extra: Any,
) -> EventV1:
    suffix = extra.pop("suffix", "")
    event = EventV1(
        event_id=f"{state.run_id}:{entry['seq']}{suffix}",
        run_id=state.run_id,
        trace_id=state.trace_id,
        timestamp_utc=str(entry["ts"]),
        actor_role=actor,
        event_type=event_type,
        status=status,
        message_summary=_clip(summary),
        source_trace_ref=f"trace.jsonl#seq={entry['seq']}@{str(entry['hash'])[:12]}",
        display_visibility=extra.pop("visibility", state.visibility),
        **extra,
    )
    state.events.append(event)
    return event


def _source(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    _emit(
        state,
        entry,
        "system",
        "source_pinned",
        "completed",
        f"Pinned source {data.get('dataset_id')} ({data.get('licence')}).",
        evidence_refs=[f"sha256:{data.get('sha256')}"],
    )


def _start(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    if state.agent_role is None:
        _question(state, entry)
    budget = data.get("budget", {})
    who = "Engineer" if state.agent_role == "geospatial_engineer" else "Investigator"
    _emit(
        state,
        entry,
        _agent(state),
        "run_started",
        "executed",
        f"{who} started on {data.get('provider')} / {data.get('model')}; budget "
        f"{budget.get('max_turns')} turns, {budget.get('max_tool_calls')} tool calls, "
        f"{budget.get('max_usd')} USD.",
    )


def _question(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    question = "Held-out question (text withheld)." if state.heldout else data.get("question", "")
    _emit(
        state,
        entry,
        "human_director",
        "task_proposed",
        "proposed",
        f"Research question: {question}",
        receiver_role=_agent(state),
        suffix=".q",
    )


def _safety(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    allowed = bool(data.get("allowed"))
    verdict = "allowed" if allowed else f"blocked by {data.get('blocked_by') or 'policy'}"
    _emit(
        state,
        entry,
        "safety_gate",
        "safety_checked",
        "approved" if allowed else "blocked",
        f"Safety check on the {data.get('stage')}: {verdict}.",
    )


def _model_turn(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    actor: ActorRole = data.get("role") or _agent(state)
    names = [str(c.get("name")) for c in data.get("tool_calls", [])]
    seconds = data.get("wall_seconds")
    elapsed = None if seconds is None else round(float(seconds) * 1000)
    if names:
        event = _emit(
            state,
            entry,
            actor,
            "tool_requested",
            "proposed",
            f"Turn {data.get('turn')}: requested {', '.join(names)}.",
            receiver_role="system" if actor == "product_manager" else "tool",
            elapsed_ms=elapsed,
        )
    else:
        event = _emit(
            state,
            entry,
            actor,
            "answer_submitted",
            "proposed",
            f"Turn {data.get('turn')}: drafted the final answer.",
            elapsed_ms=elapsed,
        )
    state.last_model_event = event.event_id


def _arguments(raw: Any) -> str:
    try:
        args = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return "unparsed arguments"
    if not isinstance(args, dict):
        return "arguments"
    simple = [f"{k}={v}" for k, v in args.items() if isinstance(v, str | int | float)]
    return ", ".join(simple) or ", ".join(sorted(args))


def _tool_refs(data: dict[str, Any]) -> list[str]:
    source = data.get("source")
    digest = source.get("sha256") if isinstance(source, dict) else None
    return [f"sha256:{digest}"] if digest else []


def _tool_result(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    name, outcome = str(data.get("name")), str(data.get("outcome"))
    status: EventStatus = {"executed": "executed", "rejected": "rejected"}.get(outcome, "failed")  # type: ignore[assignment]
    detail = f" ({data.get('error')})" if data.get("error") else ""
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    tool = _emit(
        state,
        entry,
        "tool",
        "tool_completed",
        status,
        f"{name}({_arguments(data.get('arguments'))}) -> {outcome}{detail}",
        receiver_role=_agent(state),
        parent_event_id=state.last_model_event,
        evidence_refs=_tool_refs(payload),
    )
    if name in SUBMIT_TOOLS and outcome == "executed":
        _verdicts(state, entry, payload, tool.event_id)


def _verdicts(state: _State, entry: dict[str, Any], data: dict[str, Any], parent: str) -> None:
    verdicts = data.get("verdicts", [])
    parts = [f"{v.get('id')} {v.get('verdict')} ({v.get('reason')})" for v in verdicts]
    _emit(
        state,
        entry,
        "verifier",
        "claim_verified",
        "approved" if data.get("all_supported") else "rejected",
        f"Round {data.get('round')}: " + ("; ".join(parts) or "no claims"),
        receiver_role=_agent(state),
        parent_event_id=parent,
        suffix=".v",
    )


def _skipped(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    _emit(
        state,
        entry,
        "tool",
        "tool_completed",
        "blocked",
        f"{data.get('name')} not run: {data.get('reason')}",
        receiver_role=_agent(state),
        parent_event_id=state.last_model_event,
    )


def _model_error(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    detail = ""
    if "attempt" in data:  # traces before the retry policy have no attempt fields
        tail = "; retrying" if data.get("retrying") else ""
        detail = f" (attempt {data['attempt']} of {data.get('max_attempts')}{tail})"
    summary = f"Model call failed: {data.get('kind')}{detail}."
    actor = data.get("role") or _agent(state)
    _emit(state, entry, actor, "error", "failed", summary)


def _retry_skipped(state: _State, entry: dict[str, Any]) -> None:
    reason = entry["data"].get("reason")
    _emit(state, entry, "system", "error", "blocked", f"Model call not retried: {reason}.")


def _audit(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    issues = sum(len(v) for v in data.values() if isinstance(v, list))
    issues += 1 if data.get("language") else 0
    status: EventStatus = "rejected" if issues else "approved"
    _emit(
        state,
        entry,
        "verifier",
        "claim_verified",
        status,
        f"Answer audit: {issues} issue(s) in the final text.",
        receiver_role=_agent(state),
    )


def _revision(state: _State, entry: dict[str, Any]) -> None:
    count = len(entry["data"].get("issues", []))
    _emit(
        state,
        entry,
        "verifier",
        "revision_proposed",
        "pending",
        f"Requested one answer revision for {count} issue(s).",
        receiver_role=_agent(state),
    )


def _plan_submitted(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else {}
    method = plan.get("method_choice", {}).get("selected_id")
    _emit(
        state,
        entry,
        _agent(state),
        "plan_submitted",
        "proposed",
        f"Plan revision {data.get('plan_revision')}: intent {plan.get('research_intent')}, "
        f"method {method}.",
        receiver_role="scientific_critic",
        task_id=data.get("task_id"),
        plan_revision=data.get("plan_revision"),
        evidence_refs=[f"sha256:{data.get('plan_sha256')}"],
    )


_REVIEW_STATUS: dict[str, EventStatus] = {
    "accept": "approved",
    "accept_with_warnings": "approved",
    "needs_evidence": "pending",
    "revise": "rejected",
}


def _plan_reviewed(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    findings = data.get("findings", [])
    errors = sum(1 for f in findings if f.get("severity") == "error")
    abstentions = ", ".join(data.get("abstentions", [])) or "none"
    _emit(
        state,
        entry,
        "scientific_critic",
        "plan_reviewed",
        _REVIEW_STATUS.get(str(data.get("verdict")), "failed"),
        f"Plan review: {data.get('verdict')}; {errors} error(s) of {len(findings)} "
        f"finding(s); abstentions: {abstentions}.",
        receiver_role=_agent(state),
        plan_revision=data.get("plan_revision"),
        evidence_refs=[f"sha256:{data.get('plan_sha256')}"],
    )


def _approval_requested(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    target = data.get("asset_id") or data.get("case_id")
    _emit(
        state,
        entry,
        "system",
        "approval_requested",
        "pending",
        f"Approval gate: {data.get('action')} for {target} needs a recorded human approval.",
        receiver_role="human_director",
    )


def _approval_resolved(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    approved = bool(data.get("approved"))
    detail = (
        f"covered by recorded approval {data.get('approval_id')}"
        if approved
        else f"refused: {data.get('refusal')}"
    )
    _emit(
        state,
        entry,
        "human_director",
        "approval_resolved",
        "approved" if approved else "rejected",
        f"{data.get('action')} for {data.get('target')}: {detail}.",
        receiver_role="system",
    )


def _rendered(state: _State, entry: dict[str, Any]) -> None:
    _emit(
        state,
        entry,
        "system",
        "answer_submitted",
        "executed",
        "The model text failed the answer check twice; the answer was rendered from "
        "verified findings only.",
    )


def _forced_abstention(state: _State, entry: dict[str, Any]) -> None:
    reasons = ", ".join(entry["data"].get("reasons", []))
    _emit(
        state,
        entry,
        "safety_gate",
        "safety_checked",
        "blocked",
        f"Causal-attribution question routed to a typed abstention ({reasons}); "
        "the planner did not run.",
    )


def _finish(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    status = str(data.get("status"))
    done: EventStatus = (
        "failed" if status in {"error", "refused", "failed", "provider_error"} else "completed"
    )
    _emit(
        state,
        entry,
        "system",
        "run_completed",
        done,
        f"{'Engineer task' if state.agent_role else 'Run'} finished: {status} "
        f"({data.get('reason')}); {data.get('turns', 0)} model turns.",
    )


def _workflow_start(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    _question(state, entry)
    pm, engineer = data.get("pm") or {}, data.get("engineer") or {}
    _emit(
        state,
        entry,
        "system",
        "run_started",
        "executed",
        f"Workflow started ({data.get('topology')} PM topology): product manager "
        f"{pm.get('provider')} / {pm.get('model')}, engineer {engineer.get('provider')} / "
        f"{engineer.get('model')}. The code controller owns every transition.",
        task_id=data.get("task_id"),
    )


_ROLES: dict[str, ActorRole] = {
    "product_manager": "product_manager",
    "geospatial_engineer": "geospatial_engineer",
}


def _role_invocation(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    role = _ROLES.get(str(data.get("role")))
    if role is None:
        raise UnknownEventError(f"unknown workflow role {data.get('role')!r}")
    started = data.get("phase") == "started"
    state.agent_role = role if started else None
    if started:
        _emit(
            state,
            entry,
            "system",
            "role_invocation_started",
            "executed",
            f"Invoked {role.replace('_', ' ')} for task {data.get('task_id')}.",
            receiver_role=role,
            task_id=data.get("task_id"),
        )
        return
    ok = data.get("status") not in {"failed", "provider_error"}
    _emit(
        state,
        entry,
        role,
        "role_invocation_finished",
        "completed" if ok else "failed",
        f"{role.replace('_', ' ').capitalize()} finished: {data.get('status')}; "
        f"{data.get('model_calls')} model call(s).",
        receiver_role="system",
        task_id=data.get("task_id"),
    )


def _brief_reviewed(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    valid = bool(data.get("valid"))
    detail = f"route {data.get('route')}" if valid else "; ".join(data.get("issues", []))
    digest = data.get("brief_sha256")
    _emit(
        state,
        entry,
        "system",
        "brief_validated",
        "approved" if valid else "rejected",
        f"Brief {'accepted' if valid else 'rejected'} by code checks: {detail}.",
        receiver_role="product_manager",
        task_id=data.get("task_id"),
        evidence_refs=[f"sha256:{digest}"] if digest else [],
    )


def _task_handoff(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    task = data.get("task") if isinstance(data.get("task"), dict) else {}
    _emit(
        state,
        entry,
        "system",
        "task_handoff_created",
        "approved",
        f"Engineering task {data.get('task_id')} for case {task.get('case_id')}: "
        f"{len(task.get('allowed_dataset_ids', []))} allowed dataset(s), method "
        f"{', '.join(task.get('allowed_method_ids', []))}; read-only.",
        receiver_role="geospatial_engineer",
        task_id=data.get("task_id"),
        evidence_refs=[f"sha256:{data.get('brief_sha256')}", f"sha256:{data.get('task_sha256')}"],
    )


def _result_delivered(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    reply = data.get("reply") if isinstance(data.get("reply"), dict) else {}
    found = ", ".join(reply.get("supported_finding_ids", [])) or "none"
    _emit(
        state,
        entry,
        "system",
        "verified_result_delivered",
        "completed",
        f"Engineer result {reply.get('status')} sent to the product manager; verified "
        f"findings: {found}.",
        receiver_role="product_manager",
        task_id=data.get("task_id"),
        evidence_refs=[f"sha256:{data.get('reply_sha256')}"],
    )


def _pm_report(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    passed = bool(data.get("passed"))
    source = data.get("source")
    text = (
        "passed the answer audit"
        if passed
        else f"failed ({len(data.get('issues', []))} issue(s)); shown: {source} answer"
    )
    _emit(
        state,
        entry,
        "product_manager",
        "pm_report_issued",
        "approved" if passed else "rejected",
        f"Product manager report {text}.",
        receiver_role="human_director",
    )


HANDLERS = {
    ("workflow_start", "runtime"): _workflow_start,
    ("role_invocation", "runtime"): _role_invocation,
    ("brief_reviewed", "runtime"): _brief_reviewed,
    ("task_handoff", "runtime"): _task_handoff,
    ("result_delivered", "runtime"): _result_delivered,
    ("pm_report", "runtime"): _pm_report,
    ("source", "runtime"): _source,
    ("start", "runtime"): _start,
    ("safety_check", "safety"): _safety,
    ("model_turn", "model"): _model_turn,
    ("tool_result", "runtime"): _tool_result,
    ("tool_skipped", "runtime"): _skipped,
    ("model_error", "runtime"): _model_error,
    ("model_retry_skipped", "runtime"): _retry_skipped,
    ("answer_audit", "verifier"): _audit,
    ("answer_revision", "verifier"): _revision,
    ("plan_submitted", "model"): _plan_submitted,
    ("plan_reviewed", "critic"): _plan_reviewed,
    ("approval_requested", "approval_gate"): _approval_requested,
    ("approval_resolved", "approval_gate"): _approval_resolved,
    ("answer_rendered", "runtime"): _rendered,
    ("forced_abstention", "safety"): _forced_abstention,
    ("finish", "runtime"): _finish,
}


def looks_heldout(run_dir: Path) -> bool:
    """A run is treated as held-out when any part of its path names the held-out set."""
    return any(HELDOUT_MARK in part.lower() for part in run_dir.resolve().parts)


def _check_result(run_dir: Path, records: list[dict[str, Any]]) -> str | None:
    finish = next((r for r in reversed(records) if r["event"] == "finish"), None)
    path = run_dir / "result.json"
    if not path.is_file():
        return None if finish is None else str(finish["data"].get("status"))
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResultMismatchError("result.json is not valid JSON") from exc
    status = str(result.get("status"))
    if finish is None or str(finish["data"].get("status")) != status:
        raise ResultMismatchError("result.json status differs from the trace finish record")
    return status


def load_run(run_dir: Path, *, heldout: bool | None = None) -> RunEvents:
    """Verify the trace, then map every record. Raise on any doubt; never guess."""
    path = run_dir / "trace.jsonl"
    if not path.is_file():
        raise TraceMissingError(f"no trace.jsonl in {run_dir.name}")
    trace = RunTrace(path)
    count = trace.verify()
    if count == 0:
        raise TraceMissingError(f"empty trace in {run_dir.name}")
    records = list(trace.records())
    held = looks_heldout(run_dir) if heldout is None else heldout
    head = str(records[-1]["hash"])
    state = _State(
        run_id=run_dir.name,
        trace_id=head[:16],
        visibility=Visibility.INTERNAL if held else Visibility.PUBLIC_DEMO,
        heldout=held,
    )
    for entry in records:
        handler = HANDLERS.get((str(entry.get("event")), str(entry.get("actor"))))
        if handler is None:
            raise UnknownEventError(
                f"unknown event {entry.get('event')!r} by {entry.get('actor')!r}"
            )
        handler(state, entry)
    status = _check_result(run_dir, records)
    closed = records[-1]["event"] == "finish"
    return RunEvents(run_dir.name, count, head, closed, held, status, state.events)
