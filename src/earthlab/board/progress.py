"""The stage and task tree of one run, computed from its trace records and nothing else.

Saved runs, replay copies and a run still in progress all pass through `fold`, so no view
can show a task or a status that the hash-chained trace does not hold. A task is born in
the status its first record proves. A move the status rules refuse raises IllegalMove.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

TaskStatus = Literal[
    "proposed",
    "scoped",
    "authorized",
    "queued",
    "running",
    "review",
    "verified",
    "needs_revision",
    "blocked",
    "failed",
    "cancelled",
]
MOVES: dict[str, frozenset[str]] = {
    "proposed": frozenset({"scoped", "cancelled"}),
    "scoped": frozenset({"authorized", "blocked", "cancelled"}),
    "authorized": frozenset({"queued", "cancelled"}),
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"review", "blocked", "failed", "cancelled"}),
    "review": frozenset({"verified", "needs_revision", "blocked", "failed", "cancelled"}),
    "needs_revision": frozenset({"running", "cancelled"}),
    "blocked": frozenset({"queued", "cancelled"}),
    "verified": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}
# A run outcome and the task status it proves. Only `verified` passed every check. The
# other reportable outcomes stay in review: an abstention is correct, but it is not a
# verified result, and a person reads it.
OUTCOME_STATUS: dict[str, TaskStatus] = {
    "verified": "verified",
    "needs_revision": "needs_revision",
    "awaiting_human": "review",
    "partial": "review",
    "abstained": "review",
    "answer_unverified": "review",
    "no_supported_findings": "review",
    "needs_input": "blocked",
    "refused": "cancelled",
    "out_of_scope": "cancelled",
    "budget_exhausted": "failed",
    "provider_error": "failed",
    "failed": "failed",
}
_NEEDS_REVIEW = frozenset({"verified", "needs_revision", "partial", "abstained"})
_ROLE_WORK = {
    "product_manager": "Product manager is writing the brief",
    "orchestrator": "Orchestrator is deciding the next stage",
    "geospatial_engineer": "Geospatial Lead is working",
    "data_specialist": "Data specialist is working on its ticket",
    "ml_engineer": "ML/DL engineer is running the approved template",
}


class IllegalMove(ValueError):
    """The trace asks for a task status change that the rules refuse."""


@dataclass
class TaskRow:
    task_id: str
    parent_task_id: str | None
    owner: str
    status: TaskStatus
    outcome: str | None = None
    input_sha256: str | None = None
    output_sha256: str | None = None
    blocked_reason: str | None = None


@dataclass
class Progress:
    run_id: str
    kind: Literal["workflow", "direct"] = "direct"
    stage: str = "Waiting for the first trace record"
    status: str | None = None
    closed: bool = False
    records: int = 0
    head: str = ""
    model_calls: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tasks: dict[str, TaskRow] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    root: str | None = None


def move(task: TaskRow, status: TaskStatus) -> None:
    if status not in MOVES[task.status]:
        raise IllegalMove(f"{task.task_id}: {task.status} -> {status}")
    task.status = status


def settle(task: TaskRow, outcome: str, reason: str | None = None) -> None:
    """End a running task with the status its outcome proves. An unknown outcome fails."""
    target = OUTCOME_STATUS.get(outcome, "failed")
    task.outcome = outcome
    if target == "review" or outcome in _NEEDS_REVIEW:
        move(task, "review")
    if task.status != target:
        move(task, target)
    if target == "blocked":
        task.blocked_reason = reason or outcome


def _note(view: Progress, text: str) -> None:
    view.stage = text
    view.notes.append(text)


def _start_workflow(view: Progress, data: dict[str, Any]) -> None:
    task_id = str(data["task_id"])
    view.kind, view.root = "workflow", task_id
    view.tasks[task_id] = TaskRow(task_id, None, "product_manager", "running")
    _note(view, "Request received; safety check on the question")


def _start_delegation(view: Progress, data: dict[str, Any]) -> None:
    task_id = str(data["task_id"])
    view.kind, view.root = "workflow", task_id
    view.tasks[task_id] = TaskRow(
        task_id, None, "geospatial_engineer", "running", input_sha256=data.get("parent_trace_head")
    )
    _note(view, f"Delegation under run {data.get('parent_run_id')}")


EXPERIMENT_OWNER = {"team": "product_manager", "single": "geospatial_engineer"}


def _start_experiment(view: Progress, data: dict[str, Any]) -> None:
    task_id = str(data["task_id"])
    view.kind, view.root = "workflow", task_id
    owner = EXPERIMENT_OWNER.get(str(data.get("arm")), "controller")
    view.tasks[task_id] = TaskRow(task_id, None, owner, "running")
    _note(view, f"Historical evaluation E1, arm {data.get('arm')}")


def _start_direct(view: Progress) -> None:
    task_id = f"{view.run_id}.investigate"
    view.root = task_id
    view.tasks[task_id] = TaskRow(task_id, None, "orchestrator", "running")


def _invocation(view: Progress, data: dict[str, Any]) -> None:
    role, task = str(data["role"]), view.tasks.get(str(data["task_id"]))
    if data["phase"] == "started":
        if task is not None and task.status == "queued":
            move(task, "running")
        _note(view, _ROLE_WORK.get(role, f"{role} is working"))
    elif task is not None and task.task_id != view.root:
        settle(task, str(data["status"]))


def _handoff(view: Progress, data: dict[str, Any]) -> None:
    task_id = str(data["task_id"])
    view.tasks[task_id] = TaskRow(
        task_id,
        str(data["parent_task_id"]),
        str(data["receiver"]),
        "queued",
        input_sha256=str(data["task_sha256"]),
    )
    _note(view, f"Task handed to the {str(data['receiver']).replace('_', ' ')}")


def _brief(view: Progress, data: dict[str, Any]) -> None:
    if view.root is not None:
        view.tasks[view.root].input_sha256 = data.get("brief_sha256")
    _note(view, f"Typed brief checked by code: valid {data['valid']}, {data['route']}")


def _delivered(view: Progress, data: dict[str, Any]) -> None:
    task = view.tasks.get(str(data["task_id"]))
    if task is not None:
        task.output_sha256 = data.get("reply_sha256")
    _note(view, "Verified result delivered; product manager is writing the report")


def _finish(view: Progress, data: dict[str, Any]) -> None:
    status = str(data.get("status"))
    if view.kind == "workflow" and not data.get("workflow"):
        _note(view, f"Engineer run finished: {status}")
        return
    view.status, view.closed = status, True
    if view.root is not None:
        settle(view.tasks[view.root], status, str(data.get("reason") or status))
    _note(view, f"Finished: {status}")


def _usage(view: Progress, data: dict[str, Any]) -> None:
    view.model_calls += 1
    usage = data.get("usage") or {}
    view.prompt_tokens += int(usage.get("prompt_tokens") or 0)
    view.completion_tokens += int(usage.get("completion_tokens") or 0)
    names = ", ".join(str(c["name"]) for c in data.get("tool_calls") or []) or "final answer"
    role = str(data.get("role") or "model").replace("_", " ")
    _note(view, f"Turn {data.get('turn')} ({role}): chose {names}")


def _tool(view: Progress, data: dict[str, Any]) -> None:
    view.tool_calls += 1
    _note(view, f"{data.get('name')}: {data.get('outcome')}")


def _safety(view: Progress, data: dict[str, Any]) -> None:
    verdict = "allowed" if data.get("allowed") else f"blocked ({data.get('reason')})"
    _note(view, f"Safety check on the {data.get('stage')}: {verdict}")


_HANDLERS = {
    "role_invocation": _invocation,
    "task_handoff": _handoff,
    "brief_reviewed": _brief,
    "result_delivered": _delivered,
    "finish": _finish,
    "model_turn": _usage,
    "tool_result": _tool,
    "safety_check": _safety,
}


def apply(view: Progress, entry: dict[str, Any]) -> None:
    event, data = str(entry["event"]), entry["data"]
    view.records += 1
    view.head = str(entry["hash"])
    if event == "workflow_start":
        _start_workflow(view, data)
    elif event == "experiment_start":
        _start_experiment(view, data)
    elif event == "delegation_start":
        _start_delegation(view, data)
    elif view.root is None:
        _start_direct(view)
    handler = _HANDLERS.get(event)
    if handler is not None:
        handler(view, data)
    elif event == "plan_reviewed":
        _note(view, f"Plan critic (code): {data.get('verdict')}")
    elif event == "acceptance_checked":
        _note(view, f"Acceptance checks (code): passed {data.get('passed')}")
    elif event == "lead_reviewed":
        _note(view, f"Lead review: accepted {data.get('accepted')}")


def fold(run_id: str, entries: Iterable[dict[str, Any]]) -> Progress:
    view = Progress(run_id)
    for entry in entries:
        apply(view, entry)
    return view
