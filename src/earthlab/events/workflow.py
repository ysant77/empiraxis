"""Event mapping for the product manager -> engineer workflow trace entries."""

from __future__ import annotations

from typing import Any

from earthlab.events.contract import ActorRole
from earthlab.events.emit import State, UnknownEventError, emit, question_event


def _workflow_start(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    question_event(state, entry)
    pm, engineer = data.get("pm") or {}, data.get("engineer") or {}
    emit(
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


def _role_invocation(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    role = _ROLES.get(str(data.get("role")))
    if role is None:
        raise UnknownEventError(f"unknown workflow role {data.get('role')!r}")
    started = data.get("phase") == "started"
    state.agent_role = role if started else None
    if started:
        emit(
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
    emit(
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


def _brief_reviewed(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    valid = bool(data.get("valid"))
    detail = f"route {data.get('route')}" if valid else "; ".join(data.get("issues", []))
    digest = data.get("brief_sha256")
    emit(
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


def _task_handoff(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    task = data.get("task") if isinstance(data.get("task"), dict) else {}
    emit(
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


def _result_delivered(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    reply = data.get("reply") if isinstance(data.get("reply"), dict) else {}
    found = ", ".join(reply.get("supported_finding_ids", [])) or "none"
    emit(
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


def _pm_report(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    passed = bool(data.get("passed"))
    source = data.get("source")
    text = (
        "passed the answer audit"
        if passed
        else f"failed ({len(data.get('issues', []))} issue(s)); shown: {source} answer"
    )
    emit(
        state,
        entry,
        "product_manager",
        "pm_report_issued",
        "approved" if passed else "rejected",
        f"Product manager report {text}.",
        receiver_role="human_director",
    )


WORKFLOW_HANDLERS = {
    ("workflow_start", "runtime"): _workflow_start,
    ("role_invocation", "runtime"): _role_invocation,
    ("brief_reviewed", "runtime"): _brief_reviewed,
    ("task_handoff", "runtime"): _task_handoff,
    ("result_delivered", "runtime"): _result_delivered,
    ("pm_report", "runtime"): _pm_report,
}
