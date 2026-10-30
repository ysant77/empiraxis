"""Shared pieces of the event adapter: run state, errors and the one emit function."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from earthlab.events.contract import ActorRole, EventStatus, EventType, EventV1, Visibility

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
class State:
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


def acting_role(state: State) -> ActorRole:
    """The model role acting now: a workflow role, else the single Muse investigator."""
    return state.agent_role or "orchestrator"


def clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _SUMMARY_LIMIT else text[: _SUMMARY_LIMIT - 3] + "..."


def emit(
    state: State,
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
        message_summary=clip(summary),
        source_trace_ref=f"trace.jsonl#seq={entry['seq']}@{str(entry['hash'])[:12]}",
        display_visibility=extra.pop("visibility", state.visibility),
        **extra,
    )
    state.events.append(event)
    return event


def question_event(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    question = "Held-out question (text withheld)." if state.heldout else data.get("question", "")
    emit(
        state,
        entry,
        "human_director",
        "task_proposed",
        "proposed",
        f"Research question: {question}",
        receiver_role=acting_role(state),
        suffix=".q",
    )
