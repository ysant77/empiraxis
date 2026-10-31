"""The separate topology's orchestrator: one typed decision, checked by code, one correction.

The orchestrator model reads the validated brief and proposes the next stage with its
only tool, `submit_decision`. Code accepts the decision only when it fits the brief: the
engineer can be assigned only the brief's case, a clarification may add no figure, and the
decision has no field that could grant a permission, approve spending or verify a claim.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from earthlab.agent.budget import Budget, BudgetMeter
from earthlab.agent.messages import assistant_message
from earthlab.digest import payload_digest
from earthlab.llm.types import ChatResponse
from earthlab.tools.registry import ToolSpec
from earthlab.workflow.brief import invented_numbers
from earthlab.workflow.calls import RoleCalls
from earthlab.workflow.contracts import DecisionProposal, OrchestratorDecisionV1, ProductBriefV1
from earthlab.workflow.prompts import ORCHESTRATOR_SYSTEM

SUBMIT_DECISION = "submit_decision"
ORCHESTRATOR_CALLS = 2  # the decision and one correction


def decision_spec() -> ToolSpec:
    return ToolSpec(
        SUBMIT_DECISION,
        "Submit the next workflow stage. This is your only tool.",
        DecisionProposal,
        lambda _: {},
    )


def validate_decision(decision: DecisionProposal, brief: ProductBriefV1, request: str) -> list[str]:
    """Why code will not execute the decision; empty when it will."""
    issues = []
    if decision.decision == "assign_engineer" and decision.case_id != brief.brief.case_id:
        issues.append(f"assign_engineer must name the brief's case {brief.brief.case_id}")
    if decision.decision == "request_input" and not decision.clarification:
        issues.append("request_input must give the clarification to ask")
    if decision.decision != "request_input" and decision.clarification:
        issues.append("only request_input carries a clarification")
    written = f"{decision.reason} {decision.clarification or ''}"
    context = f"{request} {brief.brief.normalized_question}"
    if invented := invented_numbers(written, context):
        issues.append(f"numbers not in the request or the brief: {', '.join(invented)}")
    return issues


def _read(
    resp: ChatResponse, brief: ProductBriefV1, request: str
) -> tuple[DecisionProposal | None, list[str]]:
    calls = [c for c in resp.tool_calls if c.name == SUBMIT_DECISION]
    if not calls:
        return None, ["no decision was submitted; call submit_decision"]
    try:
        decision = DecisionProposal.model_validate_json(calls[0].arguments)
    except ValidationError as exc:
        return None, [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()][:6]
    return decision, validate_decision(decision, brief, request)


def propose_decision(
    orchestrator: RoleCalls, brief: ProductBriefV1, request: str, budget: Budget
) -> tuple[OrchestratorDecisionV1 | None, list[str]]:
    """The validated decision, or None with the last issues. The orchestrator sees the
    brief, not the researcher's raw request."""
    meter = BudgetMeter(
        budget.model_copy(update={"max_turns": min(budget.max_turns, ORCHESTRATOR_CALLS)})
    )
    dumped = brief.model_dump(mode="json")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": ORCHESTRATOR_SYSTEM},
        {"role": "user", "content": json.dumps(dumped["brief"], default=str)},
    ]
    issues = ["no decision was submitted"]
    for _ in range(ORCHESTRATOR_CALLS):
        resp = orchestrator.call(meter, messages, [decision_spec().schema()], "auto")
        messages.append(assistant_message(resp))
        decision, issues = _read(resp, brief, request)
        record = None
        if decision is not None and not issues:
            record = OrchestratorDecisionV1(
                task_id=brief.task_id,
                brief_sha256=payload_digest(dumped),
                decision=decision,
                author=orchestrator.identity(),
            )
        orchestrator.trace.append(
            "decision_reviewed", "runtime", task_id=brief.task_id, valid=record is not None,
            issues=issues, decision=None if decision is None else decision.decision,
            record=None if record is None else record.model_dump(mode="json"),
        )  # fmt: skip
        if record is not None:
            return record, []
        for call in resp.tool_calls:
            body = json.dumps({"issues": issues})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": body})
        if not resp.tool_calls:
            messages.append({"role": "user", "content": "Fix: " + "; ".join(issues)})
    return None, issues
