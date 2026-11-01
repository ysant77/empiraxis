"""Typed contracts for one method decision. Records only: nothing here fits or runs a method.

A proposer (a model or a person) submits a `MethodProposalV1`. Trusted code registers the
`EvaluationPlan` by digest before any evaluation, measures the candidates, and writes a
`MethodDecisionV1`. The decision has no field that can approve itself: a person records a
`HumanMethodApproval` for one exact decision digest.

The evidence label is fixed to "synthetic harness". This pilot accepts synthetic data only.
"""

from __future__ import annotations

import json
import math
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from earthlab.contracts import Strict
from earthlab.implement.contracts import SHA256, TASK_ID, WorkerPermissions, sha256_text

METHOD_ID = r"^[a-z0-9][a-z0-9_]{0,39}$"
CHECK_ID = r"^[a-z0-9_]{1,40}$"
MIN_GAIN_FLOOR = 0.05  # A plan can ask for more than this, never for less.

MethodKind = Literal["deterministic", "statistical", "ml", "dl", "pretrained"]
DataClassification = Literal["synthetic_development"]
Outcome = Literal["keep_baseline", "select_candidate", "abstain"]
ReasonCode = Literal[
    "gain_cleared_threshold",
    "gain_below_threshold",
    "gain_not_stable",
    "proposal_refused",
    "plan_not_registered",
    "dataset_mismatch",
    "data_unsuitable",
    "evaluation_undefined",
]
_ABSTAIN_CODES = frozenset(
    {
        "proposal_refused", "plan_not_registered", "dataset_mismatch", "data_unsuitable",
        "evaluation_undefined",
    }
)  # fmt: skip


def canonical_digest(record: BaseModel) -> str:
    """SHA-256 of a record's sorted JSON form. Two equal records give one digest."""
    text = json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return sha256_text(text)


class MethodCandidate(Strict):
    """One proposed route. The estimates are claims; a suitability check measures the data."""

    candidate_id: str = Field(pattern=METHOD_ID)
    kind: MethodKind
    summary: str = Field(min_length=1, max_length=200)
    estimated_min_train_samples: int = Field(ge=1, le=1_000_000)
    estimated_compute_seconds: float = Field(ge=0, le=3600, allow_inf_nan=False)


class EvaluationPlan(Strict):
    """The rule of the comparison, fixed by digest before any score exists."""

    split: Literal["chronological"] = "chronological"
    metric: Literal["mae"] = "mae"
    horizon_steps: Literal[1] = 1
    train_fraction: float = Field(ge=0.5, le=0.8, allow_inf_nan=False)
    embargo_steps: int = Field(ge=1, le=30)
    min_relative_gain: float = Field(ge=MIN_GAIN_FLOOR, le=0.9, allow_inf_nan=False)
    ci_percent: Literal[90] = 90
    bootstrap_resamples: int = Field(ge=200, le=5000)
    bootstrap_block: int = Field(ge=2, le=30)
    bootstrap_seed: int = Field(ge=0)
    dataset_sha256: str = Field(pattern=SHA256)


class MethodProposalV1(Strict):
    """Untrusted input. It has no field for a score, an approval or code."""

    schema_version: Literal["1"] = "1"
    task_id: str = Field(pattern=TASK_ID)
    proposer_role: Literal["geospatial_engineer"] = "geospatial_engineer"
    data_classification: DataClassification
    candidates: tuple[MethodCandidate, ...] = Field(min_length=2, max_length=6)
    baseline_id: str = Field(pattern=METHOD_ID)
    plan: EvaluationPlan
    unresolved_risks: tuple[str, ...] = Field(default=(), max_length=8)
    rationale: str = Field(default="", max_length=500)
    permissions: WorkerPermissions = WorkerPermissions()

    @model_validator(mode="after")
    def _risk_size(self) -> Self:
        if any(not 1 <= len(risk) <= 200 for risk in self.unresolved_risks):
            raise ValueError("each risk is one to 200 characters")
        return self


class SuitabilityCheck(Strict):
    """A data check that trusted code measured."""

    check_id: str = Field(pattern=CHECK_ID)
    passed: bool
    observed: str = Field(max_length=80)
    required: str = Field(max_length=80)


class CandidateScore(Strict):
    candidate_id: str = Field(pattern=METHOD_ID)
    mae: float = Field(ge=0, allow_inf_nan=False)


class MeasuredComparison(Strict):
    """Scores from one chronological split, written by trusted code."""

    baseline: CandidateScore
    challenger: CandidateScore
    relative_gain: float = Field(allow_inf_nan=False)
    ci_low: float = Field(allow_inf_nan=False)
    ci_high: float = Field(allow_inf_nan=False)
    train_pairs: int = Field(ge=1)
    train_end: int = Field(ge=1)
    test_start: int = Field(ge=1)
    test_samples: int = Field(ge=1)

    def clears(self, plan: EvaluationPlan) -> bool:
        """The whole selection rule: the gain reaches the plan and its interval excludes zero."""
        return self.relative_gain >= plan.min_relative_gain and self.ci_low > 0


class HumanApprovalRequirement(Strict):
    """Every decision waits for a person. No decision can record its own approval."""

    required: Literal[True] = True
    status: Literal["pending"] = "pending"
    scope: Literal["review_pilot_result_only"] = "review_pilot_result_only"


class MethodDecisionV1(Strict):
    """One decision. The validators hold the rule, so a forged record fails to load."""

    schema_version: Literal["1"] = "1"
    task_id: str = Field(pattern=TASK_ID)
    evidence_label: Literal["synthetic harness"] = "synthetic harness"
    data_classification: DataClassification = "synthetic_development"
    candidates: tuple[MethodCandidate, ...] = ()
    baseline_id: str | None = None
    plan: EvaluationPlan | None = None
    plan_sha256: str | None = Field(default=None, pattern=SHA256)
    suitability: tuple[SuitabilityCheck, ...] = ()
    comparison: MeasuredComparison | None = None
    unresolved_risks: tuple[str, ...] = Field(default=(), max_length=20)
    outcome: Outcome
    selected_id: str | None = None
    reason_code: ReasonCode
    reason: str = Field(min_length=1, max_length=600)
    human_approval: HumanApprovalRequirement = HumanApprovalRequirement()

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.plan is not None and self.plan_sha256 != canonical_digest(self.plan):
            raise ValueError("plan_sha256 does not match the plan")
        if self.outcome == "abstain":
            self._check_abstention()
        else:
            self._check_selection()
        return self

    def _check_abstention(self) -> None:
        if self.selected_id is not None or self.comparison is not None:
            raise ValueError("an abstention selects nothing and carries no scores")
        if self.reason_code not in _ABSTAIN_CODES:
            raise ValueError("an abstention needs an abstention reason")

    def _check_selection(self) -> None:
        if self.plan is None or self.comparison is None:
            raise ValueError("a selection needs a plan and a comparison")
        if not self.suitability or not all(c.passed for c in self.suitability):
            raise ValueError("a selection needs passed suitability checks")
        kinds = {c.candidate_id: c.kind for c in self.candidates}
        if self.baseline_id is None or kinds.get(self.baseline_id) != "deterministic":
            raise ValueError("the baseline must be a listed deterministic candidate")
        self._check_rule(self.plan, self.comparison)

    def _check_rule(self, plan: EvaluationPlan, measured: MeasuredComparison) -> None:
        base, challenger = measured.baseline, measured.challenger
        if base.candidate_id != self.baseline_id or base.mae <= 0:
            raise ValueError("the comparison must score the baseline with a nonzero error")
        gain = 1.0 - challenger.mae / base.mae
        if not math.isclose(gain, measured.relative_gain, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("relative_gain does not match the scores")
        if measured.clears(plan):
            expected = (challenger.candidate_id, "select_candidate", "gain_cleared_threshold")
        elif measured.relative_gain < plan.min_relative_gain:
            expected = (base.candidate_id, "keep_baseline", "gain_below_threshold")
        else:
            expected = (base.candidate_id, "keep_baseline", "gain_not_stable")
        if (self.selected_id, self.outcome, self.reason_code) != expected:
            raise ValueError("the outcome does not follow the registered rule")


class HumanMethodApproval(Strict):
    """A person's answer about one exact decision. It never approves data, spend or training."""

    task_id: str = Field(pattern=TASK_ID)
    decision_sha256: str = Field(pattern=SHA256)
    decision: Literal["approve", "reject"]
    approver_kind: Literal["human"] = "human"
    approver: str = Field(min_length=1, max_length=80)


class MethodGate(Strict):
    allowed: bool
    stage: Literal["decision", "verification", "human", "approved"]
    reasons: tuple[str, ...]
