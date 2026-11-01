"""Turn a peer's request into the existing engineer task, or refuse it.

The peer's request stands where the product manager's brief stands in the workflow, and it
passes the same `validate_brief` checks. `engineering_task` then builds the task from the
registered case, so every permission comes from the server. A requested tool or dataset
outside the case is refused, not dropped: the peer learns that the scope did not widen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from earthlab.a2a.contracts import EngineerTaskRequestV1, RefusalCode, RefusalV1, RequestedBudget
from earthlab.agent.budget import Budget
from earthlab.cases.tools import CaseLibrary
from earthlab.digest import payload_digest
from earthlab.workflow.assign import task_scope
from earthlab.workflow.brief import validate_brief
from earthlab.workflow.contracts import (
    BriefProposal,
    EngineeringTaskV1,
    ProductBriefV1,
    RoleCall,
)
from earthlab.workflow.run import engineering_task


@dataclass(frozen=True)
class EngineerJob:
    """One admitted task. `budget` is what the engineer's run may spend."""

    a2a_task_id: str
    context_id: str
    peer: str
    run_dir: Path
    request: EngineerTaskRequestV1
    brief: ProductBriefV1
    task: EngineeringTaskV1
    budget: Budget


def request_digest(request: EngineerTaskRequestV1) -> str:
    return payload_digest(request.model_dump(mode="json"))


def _refusal(code: RefusalCode, detail: str) -> RefusalV1:
    return RefusalV1(code=code, detail=detail[:500])


def bounded_budget(wanted: RequestedBudget, limit: Budget) -> Budget | RefusalV1:
    """The limit with the peer's lower values applied; a higher value is refused."""
    asked = wanted.model_dump(exclude_none=True)
    above = sorted(key for key, value in asked.items() if value > getattr(limit, key))
    if above:
        return _refusal("budget_above_limit", f"above the server limit: {', '.join(above)}")
    return limit.model_copy(update=asked)


def _scope_refusal(request: EngineerTaskRequestV1, cases: CaseLibrary) -> RefusalV1 | None:
    if request.case_id not in cases.ids():
        return _refusal("unknown_case", "the case is not registered")
    scope = task_scope(cases.get(request.case_id))
    if extra := sorted(set(request.requested_tools) - scope.tools):
        return _refusal("tool_out_of_scope", f"outside the case: {', '.join(extra)}")
    if extra := sorted(set(request.requested_datasets) - scope.dataset_ids):
        return _refusal("dataset_out_of_scope", f"outside the case: {', '.join(extra)}")
    return None


def _proposal(request: EngineerTaskRequestV1) -> BriefProposal:
    return BriefProposal(
        route="engineer",
        case_id=request.case_id,
        normalized_question=request.question,
        intent=request.intent,
        target_quantity=request.target_quantity,
        period_start=request.period_start,
        period_end=request.period_end,
        constraints=request.constraints,
    )


def _brief(request: EngineerTaskRequestV1, proposal: BriefProposal, peer: str) -> ProductBriefV1:
    """The peer takes the product manager's place, and the record says so."""
    author = RoleCall(
        role_id="product_manager", provider="a2a-peer", model=peer, logical_model="a2a-peer"
    )
    return ProductBriefV1(
        task_id=request.request_id,
        request_sha256=request_digest(request),
        brief=proposal,
        author=author,
    )


def admit(
    request: EngineerTaskRequestV1,
    *,
    a2a_task_id: str,
    context_id: str,
    peer: str,
    cases: CaseLibrary,
    limit: Budget,
    run_dir: Path,
) -> EngineerJob | RefusalV1:
    """The admitted job, or the refusal. No model and no tool run here."""
    scope_refusal = _scope_refusal(request, cases)
    if scope_refusal is not None:
        return scope_refusal
    budget = bounded_budget(request.budget, limit)
    if isinstance(budget, RefusalV1):
        return budget
    proposal = _proposal(request)
    if issues := validate_brief(proposal, request.question, cases):
        return _refusal("brief_invalid", "; ".join(issues))
    brief = _brief(request, proposal, peer)
    task = engineering_task(brief, cases, budget)
    return EngineerJob(a2a_task_id, context_id, peer, run_dir, request, brief, task, budget)
