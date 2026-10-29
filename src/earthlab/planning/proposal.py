"""Build a full InvestigationPlan from the small proposal a model submits.

The model chooses the case, intent, target, datasets (and how it uses each), the catalogue
method, hypotheses and abstentions. The runtime fills every dataset fact from the
registry, the area from the case file and the feasibility from the case check. The model
never states coverage, valid fraction, product kind or delay.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from earthlab.cases.methods import CATALOGUE
from earthlab.cases.models import ApprovalAction, StudyPeriod
from earthlab.cases.tools import CaseLibrary
from earthlab.contracts import Strict
from earthlab.planning.plan import (
    AbstainCondition,
    Abstention,
    AbstentionReason,
    ApprovalRequest,
    Hypothesis,
    InvestigationPlan,
    VerificationCheck,
    VerificationPlan,
)
from earthlab.planning.registry import Registry
from earthlab.planning.resolve import catalogue_feasibility
from earthlab.planning.roles import TaskMeta
from earthlab.planning.sources import (
    Aoi,
    DataUse,
    MethodChoice,
    PlanMethod,
    SpatialSupport,
    Target,
    TimeRange,
)
from earthlab.planning.vocab import DataRole, Quantity, ResearchIntent


class DatasetUse(Strict):
    dataset_id: str = Field(min_length=1, max_length=80)
    used_as: Quantity = Field(description="The quantity you will treat this dataset as.")
    role: DataRole = Field(default="input", description="input, reference or context.")


class ProposedAbstention(Strict):
    reason: AbstentionReason
    dataset_ids: list[str] = Field(default_factory=list, max_length=4)
    note: str = Field(min_length=5, max_length=300)


class PlanProposal(Strict):
    """What the model decides. Every dataset fact comes from the registry instead."""

    case_id: str = Field(min_length=1, max_length=80)
    requested_intent: ResearchIntent = Field(description="What the question asks for.")
    research_intent: ResearchIntent = Field(description="What the plan will actually test.")
    target: Quantity
    period_start: datetime = Field(description="Inclusive, with offset. Monthly products: UTC.")
    period_end: datetime = Field(description="Exclusive, with offset.")
    datasets: list[DatasetUse] = Field(min_length=1, max_length=6)
    method_id: str = Field(min_length=1, max_length=80, description="Catalogue method ID.")
    rationale: str = Field(min_length=5, max_length=400)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=4)
    abstentions: list[ProposedAbstention] = Field(default_factory=list, max_length=3)


def _known(proposal: PlanProposal, registry: Registry) -> None:
    unknown = sorted({d.dataset_id for d in proposal.datasets} - set(registry.candidates))
    if unknown:
        raise ValueError(
            f"unregistered datasets {unknown}; registered: {sorted(registry.candidates)}"
        )
    if proposal.method_id not in CATALOGUE:
        raise ValueError(f"unknown method {proposal.method_id}; catalogue: {sorted(CATALOGUE)}")


def _method(proposal: PlanProposal, registry: Registry) -> PlanMethod:
    entry = CATALOGUE[proposal.method_id]
    seen: set[str] = set()
    inputs = []
    for use in proposal.datasets:
        if use.dataset_id in seen:
            continue
        seen.add(use.dataset_id)
        kind = registry.candidates[use.dataset_id].product_kind
        inputs.append(
            DataUse(
                dataset_id=use.dataset_id, used_as=use.used_as, assumed_kind=kind, role=use.role
            )
        )
    return PlanMethod(
        method_id=entry.method_id,
        catalogue_id=entry.method_id,
        method_class="deterministic",
        technique="area_sum" if entry.time_unit == "calendar_month_utc" else "summary_statistics",
        inputs=tuple(inputs),
        feasibility="feasible",
        runtime_estimate_s=5,
        min_valid_fraction=entry.min_valid_fraction,
    )


def _approval_requests(method: PlanMethod, registry: Registry) -> tuple[ApprovalRequest, ...]:
    pending = tuple(
        u.dataset_id
        for u in method.inputs
        if u.role != "context"
        and registry.candidates[u.dataset_id].availability == "registered_not_downloaded"
    )
    if not pending:
        return ()
    reason = "Selected inputs are registered but not downloaded."
    return (
        ApprovalRequest(
            request_id="download-inputs",
            action=ApprovalAction.DOWNLOAD,
            dataset_ids=pending,
            reason=reason,
        ),
    )


VERIFICATION = VerificationPlan(
    checks=(
        VerificationCheck(
            check_id="independent-verifier",
            description="The independent verifier recomputes every claim from pinned data.",
            independent_of_method=True,
            acceptance_threshold=0.0,
            threshold_unit="pre-registered tolerance",
        ),
    ),
    abstain_when=(
        AbstainCondition(kind="verifier_disagrees"),
        AbstainCondition(kind="coverage_gap"),
    ),
    uncertainty_statement="Only verified findings carry values; everything else is a limitation.",
)


def build_plan(
    proposal: PlanProposal,
    cases: CaseLibrary,
    registry: Registry,
    *,
    question: str,
    task_id: str,
    revision: int,
) -> InvestigationPlan:
    """The full plan for a proposal. Raises ValueError on an unknown case, dataset or method."""
    case = cases.get(proposal.case_id).case
    _known(proposal, registry)
    method = _method(proposal, registry)
    support: SpatialSupport = "named_region" if case.area.regions else "area_total"
    requests = _approval_requests(method, registry)
    plan = InvestigationPlan(
        plan_id=f"{task_id}.plan",
        plan_revision=revision,
        task=TaskMeta(task_id=task_id, role_id="orchestrator"),
        research_question=question,
        requested_intent=proposal.requested_intent,
        research_intent=proposal.research_intent,
        aoi=Aoi(
            area=case.area,
            spatial_support=support,
            boundary_source=case.case_id,
            boundary_version="config/cases",
        ),
        time_range=TimeRange(
            period=StudyPeriod(
                start=proposal.period_start,
                end=proposal.period_end,
                local_zone=case.period.local_zone,
            )
        ),
        target=_target(proposal, support),
        data_candidates=tuple(registry.candidates[u.dataset_id] for u in method.inputs),
        method_candidates=(method,),
        method_choice=MethodChoice(
            selected_id=method.method_id,
            rationale=proposal.rationale,
            evidence_refs=(f"registry:{registry.digest()}",),
        ),
        hypotheses=tuple(proposal.hypotheses),
        abstentions=_abstentions(proposal),
        approval_scope=(ApprovalAction.DOWNLOAD,) if requests else (),
        approval_requests=requests,
        verification_plan=VERIFICATION,
    )
    return _with_feasibility(plan, registry)


def _target(proposal: PlanProposal, support: SpatialSupport) -> Target:
    entry = CATALOGUE[proposal.method_id]
    return Target(
        quantity=proposal.target,
        unit=entry.output_units[0],
        temporal_resolution="hour" if entry.time_unit == "hour" else "period_total",
        spatial_support=support,
    )


def _abstentions(proposal: PlanProposal) -> tuple[Abstention, ...]:
    return tuple(
        Abstention(reason=a.reason, dataset_ids=tuple(a.dataset_ids), note=a.note)
        for a in proposal.abstentions
    )


def _with_feasibility(plan: InvestigationPlan, registry: Registry) -> InvestigationPlan:
    """Set the method's feasibility to what the case check reports, never to a claim."""
    result = catalogue_feasibility(plan, registry)
    if result is None:
        return plan
    method = plan.selected.model_copy(update={"feasibility": result.status})
    return plan.model_copy(update={"method_candidates": (method,)})
