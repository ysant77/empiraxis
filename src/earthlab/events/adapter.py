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
    question = "Held-out question (text withheld)." if state.heldout else data.get("question", "")
    _emit(
        state,
        entry,
        "human_director",
        "task_proposed",
        "proposed",
        f"Research question: {question}",
        receiver_role="orchestrator",
        suffix=".q",
    )
    budget = data.get("budget", {})
    _emit(
        state,
        entry,
        "orchestrator",
        "run_started",
        "executed",
        f"Investigator started on {data.get('provider')} / {data.get('model')}; budget "
        f"{budget.get('max_turns')} turns, {budget.get('max_tool_calls')} tool calls, "
        f"{budget.get('max_usd')} USD.",
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
    names = [str(c.get("name")) for c in data.get("tool_calls", [])]
    seconds = data.get("wall_seconds")
    elapsed = None if seconds is None else round(float(seconds) * 1000)
    if names:
        event = _emit(
            state,
            entry,
            "orchestrator",
            "tool_requested",
            "proposed",
            f"Turn {data.get('turn')}: requested {', '.join(names)}.",
            receiver_role="tool",
            elapsed_ms=elapsed,
        )
    else:
        event = _emit(
            state,
            entry,
            "orchestrator",
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
        receiver_role="orchestrator",
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
        receiver_role="orchestrator",
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
        receiver_role="orchestrator",
        parent_event_id=state.last_model_event,
    )


def _model_error(state: _State, entry: dict[str, Any]) -> None:
    kind = entry["data"].get("kind")
    _emit(state, entry, "orchestrator", "error", "failed", f"Model call failed: {kind}.")


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
        receiver_role="orchestrator",
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
        receiver_role="orchestrator",
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


def _finish(state: _State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    status = str(data.get("status"))
    done: EventStatus = "failed" if status in {"error", "refused"} else "completed"
    _emit(
        state,
        entry,
        "system",
        "run_completed",
        done,
        f"Run finished: {status} ({data.get('reason')}); {data.get('turns', 0)} model turns.",
    )


HANDLERS = {
    ("source", "runtime"): _source,
    ("start", "runtime"): _start,
    ("safety_check", "safety"): _safety,
    ("model_turn", "model"): _model_turn,
    ("tool_result", "runtime"): _tool_result,
    ("tool_skipped", "runtime"): _skipped,
    ("model_error", "runtime"): _model_error,
    ("answer_audit", "verifier"): _audit,
    ("answer_revision", "verifier"): _revision,
    ("approval_requested", "approval_gate"): _approval_requested,
    ("approval_resolved", "approval_gate"): _approval_resolved,
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
