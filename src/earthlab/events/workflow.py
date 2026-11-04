"""Event mapping for the product manager -> engineer workflow trace entries."""

from __future__ import annotations

from typing import Any

from earthlab.events.contract import ActorRole
from earthlab.events.emit import ROLE_ALIASES, State, UnknownEventError, emit, question_event


def _workflow_start(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    question_event(state, entry)
    pm, engineer = data.get("pm") or {}, data.get("engineer") or {}
    orch = (data.get("bindings") or {}).get("orchestrator")
    middle = f", orchestrator {orch['provider_id']} / {orch['model_id']}" if orch else ""
    emit(
        state,
        entry,
        "system",
        "run_started",
        "executed",
        f"Workflow started ({data.get('topology')} topology): product manager "
        f"{pm.get('provider')} / {pm.get('model')}{middle}, engineer "
        f"{engineer.get('provider')} / {engineer.get('model')}. "
        "The code controller owns every transition.",
        task_id=data.get("task_id"),
    )


_ROLES: dict[str, ActorRole] = {
    "product_manager": "product_manager",
    "orchestrator": "orchestrator",
    "geospatial_engineer": "geospatial_engineer",
    "data_specialist": "data_specialist",
    "ml_engineer": "ml_engineer",
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
    receiver = _ROLES.get(str(data.get("receiver")), "geospatial_engineer")
    emit(
        state,
        entry,
        "system",
        "task_handoff_created",
        "approved",
        f"{receiver.replace('_', ' ').capitalize()} task {data.get('task_id')} for case "
        f"{task.get('case_id')}: {len(task.get('allowed_dataset_ids', []))} allowed dataset(s), "
        f"tools {', '.join(task.get('allowed_tools', [])) or 'by case'}; read-only.",
        receiver_role=receiver,
        task_id=data.get("task_id"),
        evidence_refs=[f"sha256:{data.get('brief_sha256')}", f"sha256:{data.get('task_sha256')}"],
    )


def _result_delivered(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    reply = data.get("reply") if isinstance(data.get("reply"), dict) else {}
    found = ", ".join(reply.get("supported_finding_ids", [])) or "none"
    receiver = _ROLES.get(str(data.get("receiver")), "product_manager")
    summary = f"Engineer result {reply.get('status')} sent to the product manager; verified "
    summary += f"findings: {found}."
    if receiver != "product_manager":
        checks = reply.get("acceptance") or {}
        summary = f"Specialist table sent to the Lead; acceptance passed {checks.get('passed')}."
    emit(
        state,
        entry,
        "system",
        "verified_result_delivered",
        "completed",
        summary,
        receiver_role=receiver,
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


def _decision_reviewed(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    valid = bool(data.get("valid"))
    detail = f"decision {data.get('decision')}" if valid else "; ".join(data.get("issues", []))
    emit(
        state,
        entry,
        "system",
        "orchestrator_decision_validated",
        "approved" if valid else "rejected",
        f"Orchestrator decision {'accepted' if valid else 'rejected'} by code checks: {detail}.",
        receiver_role="orchestrator",
        task_id=data.get("task_id"),
    )


def _delegation_start(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    lead, specialist = data.get("lead") or {}, data.get("specialist") or {}
    emit(
        state,
        entry,
        "system",
        "run_started",
        "executed",
        f"Delegation under run {data.get('parent_run_id')}: Lead {lead.get('provider')} / "
        f"{lead.get('model')}, specialist {specialist.get('provider')} / "
        f"{specialist.get('model')}. The code controller owns every transition.",
        task_id=data.get("task_id"),
    )


def _ticket_reviewed(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    valid = bool(data.get("valid"))
    emit(
        state,
        entry,
        "system",
        "brief_validated",
        "approved" if valid else "rejected",
        f"Ticket proposal checked by code: valid {valid}.",
        task_id=data.get("task_id"),
    )


def _acceptance(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    passed = bool(data.get("passed"))
    emit(
        state,
        entry,
        "verifier",
        "claim_verified",
        "completed" if passed else "failed",
        f"Acceptance checks recomputed by code: passed {passed}.",
        task_id=data.get("task_id"),
    )


def _lead_reviewed(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    emit(
        state,
        entry,
        "geospatial_engineer",
        "revision_proposed",
        "completed",
        f"Lead review: accepted {data.get('accepted')}.",
        task_id=data.get("task_id"),
    )


def _experiment_start(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    emit(
        state,
        entry,
        "system",
        "run_started",
        "executed",
        f"Historical evaluation, arm {data.get('arm')}. {data.get('evidence_label')}. "
        "Not a forecast of any future date.",
        task_id=data.get("task_id"),
    )


def _proposal_reviewed(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    valid = bool(data.get("valid"))
    emit(
        state,
        entry,
        "system",
        "brief_validated",
        "approved" if valid else "rejected",
        f"Proposal {data.get('tool')} from {data.get('role')} checked by code: valid {valid}.",
    )


def _harness_transition(state: State, entry: dict[str, Any]) -> None:
    data, actor = entry["data"], entry["actor"]
    human = actor == "human"
    emit(
        state,
        entry,
        "system",
        "approval_resolved" if human else "plan_reviewed",
        "approved" if data.get("to") == "approved" else "rejected" if human else "executed",
        f"Lifecycle: {data.get('from')} to {data.get('to')}, by the {actor}.",
    )


def _artifact_stored(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    emit(
        state, entry, "system", "tool_completed", "executed",
        f"Artifact {data.get('name')} stored, sha256 {str(data.get('sha256'))[:12]}.",
    )  # fmt: skip


def _family_comparison(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    emit(
        state, entry, "system", "plan_reviewed", "executed",
        f"Both families trained: {', '.join(data.get('trained', []))}. The Lead's strategy "
        f"{data.get('lead_strategy')} is kept as the family it expects to adopt.",
    )  # fmt: skip


def _tuning_verified(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    emit(
        state, entry, "verifier", "claim_verified", "completed",
        f"Ridge penalty {data.get('alpha')} chosen on train folds; reload difference "
        f"{data.get('reload_max_abs_difference')}.",
    )  # fmt: skip


def _inference_verified(state: State, entry: dict[str, Any]) -> None:
    data = entry["data"]
    same = bool(data.get("model_sha256_matches"))
    emit(
        state, entry, "verifier", "claim_verified", "completed" if same else "failed",
        f"Model {data.get('model_id')} reloaded in isolation: hash matches {same}, "
        f"largest difference {data.get('max_abs_difference')} over {data.get('rows')} rows.",
    )  # fmt: skip


def _role_binding(state: State, entry: dict[str, Any]) -> None:
    d = entry["data"]
    emit(
        state, entry, "system", "role_bound", "executed",
        f"Seat {d.get('role')} served by {d.get('family')} {d.get('logical_model')}: checkpoint "
        f"{d.get('checkpoint_file')}, sha256 {str(d.get('checkpoint_sha256'))[:12]}, "
        f"{d.get('quantization')}.",
        receiver_role=_receiver(d.get("role")),
    )  # fmt: skip


def _receiver(role: Any) -> ActorRole | None:
    name = ROLE_ALIASES.get(str(role), str(role))
    return name if name in _ROLES or name == "qa_reviewer" else None  # type: ignore[return-value]


def _council_formed(state: State, entry: dict[str, Any]) -> None:
    d = entry["data"]
    kind = "heterogeneous" if d.get("heterogeneous") else "single-checkpoint"
    emit(
        state, entry, "system", "role_bound", "executed",
        f"Council formed ({kind}): {d.get('seats')} model seats, {d.get('distinct_checkpoints')} "
        f"distinct checkpoint(s), families {', '.join(d.get('families', []))}.",
    )  # fmt: skip


def _decision_critique(state: State, entry: dict[str, Any]) -> None:
    d = entry["data"]
    found = d.get("findings") or []
    backed = sum(bool(f.get("backed")) for f in found)
    usable = d.get("state") == "usable"
    emit(
        state, entry, "qa_reviewer", "critique_recorded", "completed" if usable else "failed",
        f"Critic ({d.get('critic_source')}) state {d.get('state')}: verdict {d.get('verdict')}, "
        f"{backed} of {len(found)} finding(s) match the evaluator. Advisory only; it sets no "
        "score, outcome or approval.",
        receiver_role="human_director",
    )  # fmt: skip


WORKFLOW_HANDLERS = {
    ("role_binding", "runtime"): _role_binding,
    ("council_formed", "runtime"): _council_formed,
    ("decision_critique", "runtime"): _decision_critique,
    ("family_comparison", "runtime"): _family_comparison,
    ("tuning_verified", "runtime"): _tuning_verified,
    ("inference_verified", "runtime"): _inference_verified,
    ("harness_transition", "controller"): _harness_transition,
    ("harness_transition", "evaluator"): _harness_transition,
    ("harness_transition", "human"): _harness_transition,
    ("artifact_stored", "runtime"): _artifact_stored,
    ("experiment_start", "runtime"): _experiment_start,
    ("proposal_reviewed", "runtime"): _proposal_reviewed,
    ("delegation_start", "runtime"): _delegation_start,
    ("ticket_reviewed", "runtime"): _ticket_reviewed,
    ("acceptance_checked", "verifier"): _acceptance,
    ("lead_reviewed", "runtime"): _lead_reviewed,
    ("decision_reviewed", "runtime"): _decision_reviewed,
    ("workflow_start", "runtime"): _workflow_start,
    ("role_invocation", "runtime"): _role_invocation,
    ("brief_reviewed", "runtime"): _brief_reviewed,
    ("task_handoff", "runtime"): _task_handoff,
    ("result_delivered", "runtime"): _result_delivered,
    ("pm_report", "runtime"): _pm_report,
}
