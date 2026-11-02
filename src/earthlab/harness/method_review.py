"""The method review before execution: a stated case, code's checks, and one bounded critique.

Every method is a candidate, not a preferred outcome. The Lead states its case, and code checks
each proposed method against the measured facts. A blocking finding refuses the method. A
material finding starts one critic call. The critic must name a falsifiable concern or a
competing experiment. Its text goes to the Lead and the person. It sets no status and no score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from earthlab.contracts import Strict
from earthlab.forecast.gate import unbacked_numbers
from earthlab.harness.contracts import (
    DatasetProfileV1,
    ExperimentPlanV1,
    MethodProposalV1,
    ProblemSpecV1,
)
from earthlab.harness.seats import Seats, Stopped
from earthlab.harness.strategy import SuitabilityReportV1

LEAD, CRITIC = "geospatial_engineer", "method_critic"
ESTIMATE_MARGIN = 2.0
STRATEGY_OF = {
    "persistence": "deterministic", "naive": "deterministic", "climatology": "deterministic",
    "raster_deterministic": "deterministic", "ridge": "statistical", "logistic": "statistical",
    "trees": "statistical", "trees_classifier": "statistical", "gru": "small_neural",
    "tcn": "small_neural", "segmentation_pretrained": "pretrained_transfer",
    "frozen_gru_logistic": "pretrained_transfer", "distilled_student": "distillation",
}  # fmt: skip
PROPOSE_SYSTEM = "You are the Geospatial Lead. Before any work runs, call propose_method. Every \
method is a candidate. State the hypothesis, the simplest suitable baseline, the alternatives, \
why the data suffice, the smallest gain that justifies the cost, the leakage risks, the compute \
seconds, and measurable failure conditions. Choose the baseline when nothing justifies more."
CRITIC_SYSTEM = "You review a method plan before it runs. Read the findings. Call submit_critique \
with one specific concern that a stated measurement can prove wrong, or one competing experiment. \
Agreement or praise is not a review. You cannot change a score, a rule or a human decision."
_PRAISE = re.compile(
    r"\b(?:looks? (?:good|fine|reasonable)|sounds? (?:good|reasonable)|well[- ]designed|"
    r"i agree|no (?:concerns?|issues?)|seems? (?:fine|appropriate|reasonable)|"
    r"excellent|great (?:plan|choice|approach)|solid (?:plan|choice|approach))\b",
    re.IGNORECASE,
)
_PLACEHOLDER = re.compile(r"^\s*(?:n/?a|none|tbd|unknown|todo|not applicable)\W*$", re.IGNORECASE)
_MEASURED = re.compile(r"\d|\b(?:mae|rmse|skill|f1|recall|precision|pr_auc|ece|brier)\b", re.I)


class ReviewCode(StrEnum):
    UNKNOWN_METHOD = "unknown_method"
    METHOD_BLOCKED = "method_blocked"
    NOT_IN_PLAN = "not_in_plan"
    OVER_BUDGET = "over_budget"
    REPEATED_PLAN = "repeated_plan"
    BASELINE_NOT_SIMPLEST = "baseline_not_simplest"
    NO_REAL_ALTERNATIVE = "no_real_alternative"
    ESTIMATE_DISAGREES = "estimate_disagrees"
    UNTESTABLE_FAILURE = "untestable_failure"
    LATENCY_NOT_NAMED = "latency_not_named"
    UNBACKED_DATA_CLAIM = "unbacked_data_claim"


BLOCKING = frozenset({
    ReviewCode.UNKNOWN_METHOD, ReviewCode.METHOD_BLOCKED, ReviewCode.NOT_IN_PLAN,
    ReviewCode.OVER_BUDGET, ReviewCode.REPEATED_PLAN,
})  # fmt: skip


class ReviewFinding(Strict):
    code: ReviewCode
    method: str | None = None
    detail: str
    blocking: bool


class FalsifiableTest(Strict):
    """A measurement that can prove the concern wrong."""

    metric: str = Field(max_length=40)
    direction: Literal["above", "below"]
    threshold: float
    samples: str = Field(min_length=5, max_length=120)


class CritiqueV1(Strict):
    """One concern. It has no field for a score, a pass mark or an approval."""

    schema_version: Literal["1"] = "1"
    kind: Literal["falsifiable_concern", "competing_experiment"]
    finding: ReviewCode
    claim: str = Field(min_length=30, max_length=400)
    test: FalsifiableTest
    competing_method: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _competing_names_a_method(self) -> CritiqueV1:
        if (self.kind == "competing_experiment") != (self.competing_method is not None):
            raise ValueError("a competing experiment names one method, and a concern names none")
        return self


class MethodReviewRecordV1(Strict):
    schema_version: Literal["1"] = "1"
    proposal: MethodProposalV1
    findings: tuple[ReviewFinding, ...]
    verdict: Literal["proceed", "refused"]
    critic_calls: int = Field(ge=0, le=1)
    critique: CritiqueV1 | None = None
    critique_state: Literal["not_triggered", "usable", "unusable"]


@dataclass(frozen=True)
class ReviewFacts:
    """Measured by code. A proposal cannot change any of these."""

    problem: ProblemSpecV1
    profile: DatasetProfileV1
    suitability: SuitabilityReportV1
    plan: ExperimentPlanV1
    estimate_seconds: float
    budget_seconds: float


def _finding(code: ReviewCode, detail: str, method: str | None = None) -> ReviewFinding:
    return ReviewFinding(code=code, method=method, detail=detail, blocking=code in BLOCKING)


def completeness(proposal: MethodProposalV1) -> list[str]:
    """Fields that say nothing. The Lead gets one correction."""
    texts = {"hypothesis": proposal.hypothesis, "data_sufficiency": proposal.data_sufficiency}
    texts |= {f"leakage_risks[{i}]": t for i, t in enumerate(proposal.leakage_risks)}
    texts |= {f"failure_conditions[{i}]": t for i, t in enumerate(proposal.failure_conditions)}
    return [f"{name} has no content" for name, text in texts.items() if _PLACEHOLDER.match(text)]


def _each_method(proposal: MethodProposalV1, facts: ReviewFacts) -> list[ReviewFinding]:
    """Suitability for every named method, with code's own reasons."""
    checks = {c.strategy: c for c in facts.suitability.checks}
    named = [proposal.proposed_method, proposal.simplest_baseline]
    named += [c.method for c in proposal.candidates]
    out = []
    for method in dict.fromkeys(named):
        strategy = STRATEGY_OF.get(method)
        if strategy is None:
            out.append(_finding(ReviewCode.UNKNOWN_METHOD, "not a registered method", method))
        elif not checks[strategy].eligible:  # type: ignore[index]
            why = "; ".join(checks[strategy].reasons)  # type: ignore[index]
            out.append(_finding(ReviewCode.METHOD_BLOCKED, f"{strategy}: {why}", method))
    return out


def _plan_and_cost(proposal: MethodProposalV1, facts: ReviewFacts) -> list[ReviewFinding]:
    out = []
    if proposal.proposed_method not in facts.plan.methods:
        detail = f"the plan runs {list(facts.plan.methods)}"
        out.append(_finding(ReviewCode.NOT_IN_PLAN, detail, proposal.proposed_method))
    if proposal.compute_seconds > facts.budget_seconds:
        detail = f"{proposal.compute_seconds:.0f} s over {facts.budget_seconds:.0f} s"
        out.append(_finding(ReviewCode.OVER_BUDGET, detail))
    if facts.estimate_seconds > proposal.compute_seconds * ESTIMATE_MARGIN:
        detail = f"code estimates {facts.estimate_seconds:.0f} s"
        out.append(_finding(ReviewCode.ESTIMATE_DISAGREES, detail))
    return out


def _case(proposal: MethodProposalV1, facts: ReviewFacts) -> list[ReviewFinding]:
    out = []
    simple = STRATEGY_OF.get(proposal.simplest_baseline)
    deterministic = "deterministic" in facts.suitability.eligible()
    if simple is not None and simple != "deterministic" and deterministic:
        detail = "a deterministic method is eligible and simpler"
        out.append(_finding(ReviewCode.BASELINE_NOT_SIMPLEST, detail, proposal.simplest_baseline))
    others = {c.method for c in proposal.candidates} - {proposal.proposed_method}
    if not others:
        out.append(_finding(ReviewCode.NO_REAL_ALTERNATIVE, "the only candidate is the proposal"))
    if not any(_MEASURED.search(text) for text in proposal.failure_conditions):
        detail = "no failure condition names a metric or a number"
        out.append(_finding(ReviewCode.UNTESTABLE_FAILURE, detail))
    latency = facts.profile.availability_latency_hours
    if latency and not any(
        re.search(r"latenc|availab", text, re.I) for text in proposal.leakage_risks
    ):
        out.append(_finding(ReviewCode.LATENCY_NOT_NAMED, f"the data have {latency} h latency"))
    known = facts.profile.model_dump(mode="json")
    for text in unbacked_numbers(proposal.data_sufficiency, known):
        out.append(_finding(ReviewCode.UNBACKED_DATA_CLAIM, text))
    return out


def check_proposal(proposal: MethodProposalV1, facts: ReviewFacts) -> list[ReviewFinding]:
    """Deterministic checks. The same inputs give the same findings."""
    return [
        *_each_method(proposal, facts), *_plan_and_cost(proposal, facts), *_case(proposal, facts),
    ]  # fmt: skip


def repeats_plan(plan: ExperimentPlanV1, earlier: ExperimentPlanV1) -> bool:
    """A refinement that changes nothing tests nothing."""
    return (plan.methods, plan.config) == (earlier.methods, earlier.config)


def critique_issues(
    value: CritiqueV1, findings: list[ReviewFinding], facts: ReviewFacts
) -> list[str]:
    """Why a critique is not a review. Praise and vague text do not count."""
    issues = []
    if value.finding not in {f.code for f in findings}:
        issues.append("finding: name one code from the findings")
    if _PRAISE.search(value.claim):
        issues.append("claim: agreement or praise is not a review")
    if value.test.metric not in facts.plan.metrics:
        issues.append(f"test.metric: use one of {list(facts.plan.metrics)}")
    method = value.competing_method
    if method is not None:
        strategy = STRATEGY_OF.get(method)
        if strategy not in facts.suitability.eligible():
            issues.append(f"competing_method: {method} is not eligible")
    return issues


def _critique(
    seats: Seats, proposal: MethodProposalV1, findings: list[ReviewFinding], facts: ReviewFacts
) -> CritiqueV1 | None:
    """One call and its one correction. An unusable critique changes nothing."""
    sent: dict[str, Any] = {
        "proposal": proposal, "findings": findings, "metrics": facts.plan.metrics,
        "eligible": facts.suitability.eligible(), "data": facts.profile,
    }  # fmt: skip
    try:
        return seats.propose(
            CRITIC, CRITIC_SYSTEM, sent, "submit_critique", CritiqueV1,
            lambda value: critique_issues(value, findings, facts),
        )  # fmt: skip
    except Stopped:
        return None


def run_review(seats: Seats, facts: ReviewFacts) -> MethodReviewRecordV1:
    """The Lead's case, code's findings, and at most one critic call."""
    sent = {
        "problem": facts.problem, "data": facts.profile, "suitability": facts.suitability,
        "plan": facts.plan, "estimate_seconds": facts.estimate_seconds,
    }  # fmt: skip
    proposal = seats.propose(
        LEAD, PROPOSE_SYSTEM, sent, "propose_method", MethodProposalV1, completeness
    )
    findings = check_proposal(proposal, facts)
    if any(f.blocking for f in findings):
        return MethodReviewRecordV1(
            proposal=proposal, findings=tuple(findings), verdict="refused", critic_calls=0,
            critique_state="not_triggered",
        )  # fmt: skip
    if not findings:
        return MethodReviewRecordV1(
            proposal=proposal, findings=(), verdict="proceed", critic_calls=0,
            critique_state="not_triggered",
        )  # fmt: skip
    critique = _critique(seats, proposal, findings, facts)
    return MethodReviewRecordV1(
        proposal=proposal, findings=tuple(findings), verdict="proceed", critic_calls=1,
        critique=critique, critique_state="usable" if critique else "unusable",
    )  # fmt: skip
