"""The versioned InvestigationPlan: one typed proposal that code can accept or reject.

The plan is data only. It holds no code, no shell command and no data values; it names
datasets and methods by ID. Validators here check structure (every reference resolves,
required parts exist). Scientific judgement lives in the critic, not in these models.

Future-facing parts (no runtime code reads them yet): task links, critique dispositions,
experiment design, causal design and the plan-only actions and quantities.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import Field, model_validator

from earthlab.cases.models import IDENT
from earthlab.contracts import Strict
from earthlab.planning.roles import PLAN_AUTHOR_ROLES, TaskMeta
from earthlab.planning.sources import (
    Aoi,
    DataCandidate,
    MethodChoice,
    PlanMethod,
    Target,
    TimeRange,
)
from earthlab.planning.vocab import ActionKind, Quantity, ResearchIntent, SampleUnit, SplitMethod

PLAN_SCHEMA_VERSION: Literal["1"] = "1"


class FeatureSpec(Strict):
    """One model input, timed relative to the forecast issue time (negative = before).

    For a forecast product, `issued_offset_hours` is when that forecast was issued.
    """

    name: str = Field(pattern=IDENT)
    dataset_id: str = Field(pattern=IDENT)
    valid_offset_hours: float
    issued_offset_hours: float | None = None


class LeakageControl(Strict):
    embargo_hours: float = Field(gt=0)
    justification: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class SplitSpec(Strict):
    method: SplitMethod
    leakage_control: LeakageControl | None = None


class ExperimentDesign(Strict):
    """Needed when the selected method fits a statistical or machine-learning model."""

    transformations: tuple[str, ...] = ()
    leakage_risks: tuple[str, ...] = ()
    sample_unit: SampleUnit
    split: SplitSpec
    baseline_ids: tuple[str, ...] = Field(min_length=1)
    metrics: tuple[str, ...] = Field(min_length=1)
    independent_reference_id: str | None = Field(default=None, pattern=IDENT)
    features: tuple[FeatureSpec, ...] = ()


class PlannedOperation(Strict):
    """A consequential step the plan wants to run. It needs a matching approval request."""

    op_id: str = Field(pattern=IDENT)
    action: ActionKind
    dataset_ids: tuple[str, ...] = ()
    estimated_bytes: int | None = Field(default=None, gt=0)
    estimated_usd: float | None = Field(default=None, ge=0)


class ApprovalRequest(Strict):
    """A request to a human. A plan can only ask; it can never hold an approval."""

    request_id: str = Field(pattern=IDENT)
    action: ActionKind
    dataset_ids: tuple[str, ...] = ()
    max_bytes: int | None = Field(default=None, gt=0)
    max_usd: float | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1)


class VerificationCheck(Strict):
    check_id: str = Field(pattern=IDENT)
    description: str = Field(min_length=1)
    independent_of_method: bool
    acceptance_threshold: float
    threshold_unit: str = Field(min_length=1)
    fixed_before_run: Literal[True] = True


class AbstainCondition(Strict):
    kind: Literal["valid_fraction_below", "coverage_gap", "method_blocked", "verifier_disagrees"]
    value: float | None = None


class VerificationPlan(Strict):
    checks: tuple[VerificationCheck, ...] = Field(min_length=1)
    abstain_when: tuple[AbstainCondition, ...] = Field(min_length=1)
    cite_source_hashes: Literal[True] = True
    uncertainty_statement: str = Field(min_length=1)


class Hypothesis(Strict):
    hypothesis_id: str = Field(pattern=IDENT)
    statement: str = Field(min_length=1)
    direction: Literal["forward", "reverse", "common_cause", "null"]


class EvidenceGap(Strict):
    """Evidence the plan needs but does not have. Declaring a gap is better than guessing."""

    gap_id: str = Field(pattern=IDENT)
    needed: Quantity
    why: str = Field(min_length=1)
    candidate_dataset_ids: tuple[str, ...] = ()


class CausalDesign(Strict):
    """Future-facing: how a causal question would be identified. Never sufficient alone."""

    identification: Literal[
        "correlation_only",
        "wind_direction_only",
        "controlled_comparison",
        "counterfactual_model",
        "natural_experiment",
    ]
    confounders: tuple[Quantity, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class FindingDisposition(Strict):
    """Future-facing: the planner's answer to one critic finding in a revised plan."""

    finding_id: str = Field(min_length=1)
    disposition: Literal["fixed", "disputed", "deferred"]
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class InvestigationPlan(Strict):
    schema_version: Literal["1"] = PLAN_SCHEMA_VERSION
    plan_id: str = Field(pattern=IDENT)
    plan_revision: int = Field(ge=1)
    task: TaskMeta
    research_question: str = Field(min_length=5)
    requested_intent: ResearchIntent
    research_intent: ResearchIntent
    intent_note: str | None = None
    aoi: Aoi
    time_range: TimeRange
    target: Target
    data_candidates: tuple[DataCandidate, ...] = Field(min_length=1)
    method_candidates: tuple[PlanMethod, ...] = Field(min_length=1)
    method_choice: MethodChoice
    experiment_design: ExperimentDesign | None = None
    causal_design: CausalDesign | None = None
    hypotheses: tuple[Hypothesis, ...] = ()
    evidence_gaps: tuple[EvidenceGap, ...] = ()
    operations: tuple[PlannedOperation, ...] = ()
    approval_scope: tuple[ActionKind, ...] = ()
    approval_requests: tuple[ApprovalRequest, ...] = ()
    verification_plan: VerificationPlan
    evidence_refs: tuple[str, ...] = ()
    critique_dispositions: tuple[FindingDisposition, ...] = ()

    @model_validator(mode="after")
    def _structure(self) -> Self:
        problems = _identity_problems(self) + _reference_problems(self)
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def dataset(self, dataset_id: str) -> DataCandidate:
        return next(d for d in self.data_candidates if d.dataset_id == dataset_id)

    def method(self, method_id: str) -> PlanMethod:
        return next(m for m in self.method_candidates if m.method_id == method_id)

    @property
    def selected(self) -> PlanMethod:
        return self.method(self.method_choice.selected_id)


def _identity_problems(plan: InvestigationPlan) -> list[str]:
    problems = []
    if plan.task.role_id not in PLAN_AUTHOR_ROLES:
        problems.append(f"role {plan.task.role_id} may not author a plan")
    if plan.plan_revision == 1 and plan.critique_dispositions:
        problems.append("a first revision has no critique to answer")
    if plan.research_intent == "prospective_prediction" and (
        plan.time_range.forecast_issue_time is None
    ):
        problems.append("a prospective prediction needs forecast_issue_time")
    for name, ids in (
        ("dataset", [d.dataset_id for d in plan.data_candidates]),
        ("method", [m.method_id for m in plan.method_candidates]),
    ):
        if len(set(ids)) != len(ids):
            problems.append(f"{name} IDs must be unique")
    return problems


def _reference_problems(plan: InvestigationPlan) -> list[str]:
    datasets = {d.dataset_id for d in plan.data_candidates}
    methods = {m.method_id for m in plan.method_candidates}
    choice = plan.method_choice
    used = [u.dataset_id for m in plan.method_candidates for u in m.inputs]
    used += [i for r in plan.approval_requests for i in r.dataset_ids]
    used += [i for o in plan.operations for i in o.dataset_ids]
    used += [i for g in plan.evidence_gaps for i in g.candidate_dataset_ids]
    named = [choice.selected_id, *(r.method_id for r in choice.rejected)]
    if choice.simpler_baseline_id:
        named.append(choice.simpler_baseline_id)
    design = plan.experiment_design
    if design is not None:
        used += [f.dataset_id for f in design.features]
        used += [design.independent_reference_id] if design.independent_reference_id else []
        named += list(design.baseline_ids)
    problems = [f"unknown dataset {i}" for i in sorted(set(used) - datasets)]
    problems += [f"unknown method {i}" for i in sorted(set(named) - methods)]
    if choice.selected_id in {r.method_id for r in choice.rejected}:
        problems.append("the selected method is also listed as rejected")
    return problems


def load_plan(path: Path) -> InvestigationPlan:
    """Read one plan from a YAML file (safe loader; no tags, no code)."""
    return InvestigationPlan.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
