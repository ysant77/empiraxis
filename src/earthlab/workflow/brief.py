"""The product manager's brief: one schema-only tool, deterministic checks, one correction."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from earthlab.agent.budget import Budget, BudgetMeter
from earthlab.agent.messages import assistant_message
from earthlab.cases.tools import CaseLibrary
from earthlab.digest import payload_digest
from earthlab.llm.types import ChatResponse
from earthlab.tools.registry import ToolSpec
from earthlab.workflow.calls import RoleCalls
from earthlab.workflow.contracts import BriefProposal, ProductBriefV1, Topology
from earthlab.workflow.prompts import PM_SYSTEM, case_catalogue

SUBMIT_BRIEF = "submit_brief"
PM_CALLS = 2  # the brief and one correction
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_UNIT_NAMES = re.compile(r"PM2\.5|PM10|ug/m3|µg/m³", re.IGNORECASE)  # names, not figures


def brief_spec() -> ToolSpec:
    return ToolSpec(
        SUBMIT_BRIEF,
        "Submit the structured research brief. This is your only tool.",
        BriefProposal,
        lambda _: {},
    )


def _numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(_UNIT_NAMES.sub(" ", text)))


def invented_numbers(written: str, source: str) -> list[str]:
    """Figures in `written` that `source` does not contain. Unit names are not figures."""
    return sorted(_numbers(written) - _numbers(source))


def _route_issues(proposal: BriefProposal, known: set[str]) -> list[str]:
    issues = []
    if proposal.case_id is not None and proposal.case_id not in known:
        issues.append(
            f"case {proposal.case_id} is not registered; known: {', '.join(sorted(known))}"
        )
    if proposal.route == "engineer" and proposal.case_id is None:
        issues.append("route engineer needs a registered case_id")
    if proposal.route == "engineer" and proposal.clarifications_needed:
        issues.append("route engineer cannot carry open clarifications; use needs_input")
    if proposal.route == "needs_input" and not proposal.clarifications_needed:
        issues.append("route needs_input must list the clarifications needed")
    if (proposal.period_start is None) != (proposal.period_end is None):
        issues.append("give both period_start and period_end, or neither")
    return issues


def validate_brief(proposal: BriefProposal, request: str, cases: CaseLibrary) -> list[str]:
    """Why the brief cannot be forwarded; empty when it can. Same inputs, same answer."""
    known = set(cases.ids())
    issues = _route_issues(proposal, known)
    case_text = ""
    if proposal.case_id in known:
        case = cases.get(str(proposal.case_id)).case
        case_text = f"{case.title} {case.question}"
        start, end = proposal.period_start, proposal.period_end
        if start is not None and end is not None:
            if start >= end:
                issues.append("period_start must be before period_end")
            elif start < case.period.start or end > case.period.end:
                issues.append(
                    f"period is outside the case period {case.period.start.date()} to "
                    f"{case.period.end.date()}"
                )
    # A product manager restates the request; it never adds a figure of its own.
    written = " ".join(
        [
            proposal.normalized_question,
            proposal.target_quantity or "",
            *proposal.constraints,
            *proposal.clarifications_needed,
        ]
    )
    if invented := invented_numbers(written, f"{request} {case_text}"):
        issues.append(f"numbers not in the request or the case: {', '.join(invented)}")
    return issues


def _read(
    resp: ChatResponse, request: str, cases: CaseLibrary
) -> tuple[BriefProposal | None, list[str]]:
    calls = [c for c in resp.tool_calls if c.name == SUBMIT_BRIEF]
    if not calls:
        return None, ["no brief was submitted; call submit_brief"]
    try:
        proposal = BriefProposal.model_validate_json(calls[0].arguments)
    except ValidationError as exc:
        return None, [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()][:6]
    return proposal, validate_brief(proposal, request, cases)


def _feedback(messages: list[dict[str, Any]], resp: ChatResponse, issues: list[str]) -> None:
    """Tell the PM why its brief was not forwarded, for its one correction."""
    for call in resp.tool_calls:
        body = json.dumps({"issues": issues})
        messages.append({"role": "tool", "tool_call_id": call.id, "content": body})
    if not resp.tool_calls:
        messages.append({"role": "user", "content": "Fix: " + "; ".join(issues)})


def propose_brief(
    pm: RoleCalls,
    request: str,
    cases: CaseLibrary,
    budget: Budget,
    task_id: str,
    topology: Topology = "combined",
) -> tuple[ProductBriefV1 | None, list[str]]:
    """The PM's brief once it passes validation, or None with the last issues."""
    # The stage budget is already cut from the run's ledger; a cap may only lower it.
    meter = BudgetMeter(budget.model_copy(update={"max_turns": min(budget.max_turns, PM_CALLS)}))
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": PM_SYSTEM.format(cases=case_catalogue(cases))},
        {"role": "user", "content": request},
    ]
    issues = ["no brief was submitted"]
    for _ in range(PM_CALLS):
        resp = pm.call(meter, messages, [brief_spec().schema()], "auto")
        messages.append(assistant_message(resp))
        proposal, issues = _read(resp, request, cases)
        brief = None
        if proposal is not None and not issues:
            brief = ProductBriefV1(
                task_id=task_id,
                request_sha256=payload_digest(request),
                topology=topology,
                brief=proposal,
                author=pm.identity(),
            )
        dumped = None if brief is None else brief.model_dump(mode="json")
        pm.trace.append(
            "brief_reviewed", "runtime", task_id=task_id, valid=brief is not None,
            issues=issues, route=None if proposal is None else proposal.route,
            brief_sha256=None if dumped is None else payload_digest(dumped), brief=dumped,
        )  # fmt: skip
        if brief is not None:
            return brief, []
        _feedback(messages, resp, issues)
    return None, issues
