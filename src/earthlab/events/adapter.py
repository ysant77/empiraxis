"""Map a recorded run folder (trace.jsonl, result.json) to EventV1 records, read-only.

The adapter verifies the trace hash chain first and fails closed on a missing, empty,
broken or unknown trace. Actor roles come only from what the trace records. The model's
raw text and reasoning are never copied into an event.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from earthlab.events.contract import ActorRole, EventStatus, Visibility
from earthlab.events.emit import (
    HELDOUT_MARK,
    SUBMIT_TOOLS,
    ResultMismatchError,
    RunEvents,
    State,
    TraceMissingError,
    UnknownEventError,
    acting_role,
    emit,
    question_event,
)
from earthlab.events.workflow import WORKFLOW_HANDLERS
from earthlab.trace import RunTrace

__all__ = [
    "HELDOUT_MARK",
    "ResultMismatchError",
    "RunEvents",
    "TraceMissingError",
    "UnknownEventError",
    "load_run",
    "looks_heldout",
]


def _source(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    emit(
        state,
        entry,
        "system",
        "source_pinned",
        "completed",
        f"Pinned source {data.get('dataset_id')} ({data.get('licence')}).",
        evidence_refs=[f"sha256:{data.get('sha256')}"],
    )


def _start(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    if state.agent_role is None:
        question_event(state, entry)
    budget = data.get("budget", {})
    who = "Engineer" if state.agent_role == "geospatial_engineer" else "Investigator"
    emit(
        state,
        entry,
        acting_role(state),
        "run_started",
        "executed",
        f"{who} started on {data.get('provider')} / {data.get('model')}; budget "
        f"{budget.get('max_turns')} turns, {budget.get('max_tool_calls')} tool calls, "
        f"{budget.get('max_usd')} USD.",
    )


def _safety(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    allowed = bool(data.get("allowed"))
    verdict = "allowed" if allowed else f"blocked by {data.get('blocked_by') or 'policy'}"
    emit(
        state,
        entry,
        "safety_gate",
        "safety_checked",
        "approved" if allowed else "blocked",
        f"Safety check on the {data.get('stage')}: {verdict}.",
    )


def _model_turn(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    actor: ActorRole = data.get("role") or acting_role(state)
    names = [str(c.get("name")) for c in data.get("tool_calls", [])]
    seconds = data.get("wall_seconds")
    elapsed = None if seconds is None else round(float(seconds) * 1000)
    if names:
        event = emit(
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
        event = emit(
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


def _tool_result(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    name, outcome = str(data.get("name")), str(data.get("outcome"))
    status: EventStatus = {"executed": "executed", "rejected": "rejected"}.get(outcome, "failed")  # type: ignore[assignment]
    detail = f" ({data.get('error')})" if data.get("error") else ""
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    tool = emit(
        state,
        entry,
        "tool",
        "tool_completed",
        status,
        f"{name}({_arguments(data.get('arguments'))}) -> {outcome}{detail}",
        receiver_role=acting_role(state),
        parent_event_id=state.last_model_event,
        evidence_refs=_tool_refs(payload),
    )
    if name in SUBMIT_TOOLS and outcome == "executed":
        _verdicts(state, entry, payload, tool.event_id)


def _verdicts(state: State, entry: dict[str, Any], data: dict[str, Any], parent: str) -> None:
    verdicts = data.get("verdicts", [])
    parts = [f"{v.get('id')} {v.get('verdict')} ({v.get('reason')})" for v in verdicts]
    emit(
        state,
        entry,
        "verifier",
        "claim_verified",
        "approved" if data.get("all_supported") else "rejected",
        f"Round {data.get('round')}: " + ("; ".join(parts) or "no claims"),
        receiver_role=acting_role(state),
        parent_event_id=parent,
        suffix=".v",
    )


def _skipped(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    emit(
        state,
        entry,
        "tool",
        "tool_completed",
        "blocked",
        f"{data.get('name')} not run: {data.get('reason')}",
        receiver_role=acting_role(state),
        parent_event_id=state.last_model_event,
    )


def _model_error(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    detail = ""
    if "attempt" in data:  # traces before the retry policy have no attempt fields
        tail = "; retrying" if data.get("retrying") else ""
        detail = f" (attempt {data['attempt']} of {data.get('max_attempts')}{tail})"
    summary = f"Model call failed: {data.get('kind')}{detail}."
    actor = data.get("role") or acting_role(state)
    emit(state, entry, actor, "error", "failed", summary)


def _retry_skipped(state: State, entry: dict[str, Any]) -> None:
    reason = entry["data"].get("reason")
    emit(state, entry, "system", "error", "blocked", f"Model call not retried: {reason}.")


def _audit(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    issues = sum(len(v) for v in data.values() if isinstance(v, list))
    issues += 1 if data.get("language") else 0
    status: EventStatus = "rejected" if issues else "approved"
    emit(
        state,
        entry,
        "verifier",
        "claim_verified",
        status,
        f"Answer audit: {issues} issue(s) in the final text.",
        receiver_role=acting_role(state),
    )


def _revision(state: State, entry: dict[str, Any]) -> None:
    count = len(entry["data"].get("issues", []))
    emit(
        state,
        entry,
        "verifier",
        "revision_proposed",
        "pending",
        f"Requested one answer revision for {count} issue(s).",
        receiver_role=acting_role(state),
    )


def _plan_submitted(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else {}
    method = plan.get("method_choice", {}).get("selected_id")
    emit(
        state,
        entry,
        acting_role(state),
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


def _plan_reviewed(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    findings = data.get("findings", [])
    errors = sum(1 for f in findings if f.get("severity") == "error")
    abstentions = ", ".join(data.get("abstentions", [])) or "none"
    emit(
        state,
        entry,
        "scientific_critic",
        "plan_reviewed",
        _REVIEW_STATUS.get(str(data.get("verdict")), "failed"),
        f"Plan review: {data.get('verdict')}; {errors} error(s) of {len(findings)} "
        f"finding(s); abstentions: {abstentions}.",
        receiver_role=acting_role(state),
        plan_revision=data.get("plan_revision"),
        evidence_refs=[f"sha256:{data.get('plan_sha256')}"],
    )


def _approval_requested(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    target = data.get("asset_id") or data.get("case_id")
    emit(
        state,
        entry,
        "system",
        "approval_requested",
        "pending",
        f"Approval gate: {data.get('action')} for {target} needs a recorded human approval.",
        receiver_role="human_director",
    )


def _approval_resolved(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    approved = bool(data.get("approved"))
    detail = (
        f"covered by recorded approval {data.get('approval_id')}"
        if approved
        else f"refused: {data.get('refusal')}"
    )
    emit(
        state,
        entry,
        "human_director",
        "approval_resolved",
        "approved" if approved else "rejected",
        f"{data.get('action')} for {data.get('target')}: {detail}.",
        receiver_role="system",
    )


def _rendered(state: State, entry: dict[str, Any]) -> None:
    emit(
        state,
        entry,
        "system",
        "answer_submitted",
        "executed",
        "The model text failed the answer check twice; the answer was rendered from "
        "verified findings only.",
    )


def _forced_abstention(state: State, entry: dict[str, Any]) -> None:
    reasons = ", ".join(entry["data"].get("reasons", []))
    emit(
        state,
        entry,
        "safety_gate",
        "safety_checked",
        "blocked",
        f"Causal-attribution question routed to a typed abstention ({reasons}); "
        "the planner did not run.",
    )


def _finish(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    status = str(data.get("status"))
    done: EventStatus = (
        "failed" if status in {"error", "refused", "failed", "provider_error"} else "completed"
    )
    emit(
        state,
        entry,
        "system",
        "run_completed",
        done,
        f"{'Engineer task' if state.agent_role else 'Run'} finished: {status} "
        f"({data.get('reason')}); {data.get('turns', 0)} model turns.",
    )


HANDLERS = {
    **WORKFLOW_HANDLERS,
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
    state = State(
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
