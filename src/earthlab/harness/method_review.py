"""The method review before execution: a stated case, code's checks, and one bounded critique.

Every method is a candidate, not a preferred outcome. The Lead states its case, and code checks
each proposed method against the measured facts. A blocking finding refuses the method. A
material finding starts one critic call. The critic must name a falsifiable concern or a
competing experiment. The Lead must answer that critique once: accept it with a revised case,
rebut it with measured facts, or leave it open. An open concern stops the run for a person. After
evaluation, code checks the recommendation against the claims. No text here sets a status or score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from earthlab.contracts import Strict
from earthlab.forecast.gate import unbacked_numbers
from earthlab.harness.claims import ClaimLadderV1
from earthlab.harness.contracts import (
    DatasetProfileV1,
    DecisionRecordV1,
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
Agreement or praise is not a review. You cannot change a score, a rule or a human decision. Use \
competing_method only with kind competing_experiment, and choose it from eligible_methods. Choose \
test.metric from metrics."
ANSWER_SYSTEM = "You are the Geospatial Lead. A critic raised one concern about your case. Call \
answer_critique once. Use accepted with a full revised_case that removes the concern, or a simpler \
method. Use rebutted with evidence_fields that name measured facts, and name the critic's metric \
in the response. Use needs_revision when neither is possible. A person then reviews the case."
_PRAISE = re.compile(
    r"\b(?:looks? (?:good|fine|reasonable)|sounds? (?:good|reasonable)|well[- ]designed|"
    r"i agree|no (?:concerns?|issues?)|seems? (?:fine|appropriate|reasonable)|"
    r"excellent|great (?:plan|choice|approach)|solid (?:plan|choice|approach))\b",
    re.IGNORECASE,
)
_PLACEHOLDER = re.compile(r"^\s*(?:n/?a|none|tbd|unknown|todo|not applicable)\W*$", re.IGNORECASE)
_MEASURED = re.compile(r"\d|\b(?:mae|rmse|skill|f1|recall|precision|pr_auc|ece|brier)\b", re.I)
_HINDSIGHT = re.compile(r"\b(?:era5|reanalysis|hindsight)\b", re.I)
_ELEVATED = re.compile(r"elevated|above 55|above_55|exceed|peak|subgroup|region", re.I)
LEARNED = frozenset({"small_neural", "pretrained_transfer", "fine_tuning", "distillation"})


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
    NO_SIMPLE_COMPARISON = "no_simple_comparison"
    ELEVATED_NOT_TESTED = "elevated_not_tested"
    HINDSIGHT_AS_FORECAST = "hindsight_as_forecast"
    ADOPT_WITHOUT_GAIN = "adopt_without_gain"
    SUBGROUP_FAILURE = "subgroup_failure"


BLOCKING = frozenset({
    ReviewCode.UNKNOWN_METHOD, ReviewCode.METHOD_BLOCKED, ReviewCode.NOT_IN_PLAN,
    ReviewCode.OVER_BUDGET, ReviewCode.REPEATED_PLAN, ReviewCode.HINDSIGHT_AS_FORECAST,
    ReviewCode.ADOPT_WITHOUT_GAIN,
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


class DispositionV1(Strict):
    """The Lead's one answer to one critique. It has no field for a score or an approval."""

    schema_version: Literal["1"] = "1"
    disposition: Literal["accepted", "rebutted", "needs_revision"]
    response: str = Field(min_length=30, max_length=400)
    revised_case: MethodProposalV1 | None = None
    evidence_fields: tuple[str, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def _each_answer_has_its_evidence(self) -> DispositionV1:
        if (self.disposition == "accepted") != (self.revised_case is not None):
            raise ValueError("accepted needs revised_case, and no other answer takes one")
        if (self.disposition == "rebutted") != bool(self.evidence_fields):
            raise ValueError("rebutted needs evidence_fields, and no other answer takes them")
        return self


class MethodReviewRecordV1(Strict):
    schema_version: Literal["1"] = "1"
    proposal: MethodProposalV1
    findings: tuple[ReviewFinding, ...]
    verdict: Literal["proceed", "refused", "needs_revision"]
    critic_calls: int = Field(ge=0, le=1)
    critique: CritiqueV1 | None = None
    critique_state: Literal["not_triggered", "usable", "unusable"]
    critic_source: Literal["not_used", "independent_model", "same_model_second_pass"] = "not_used"
    lead_responses: int = Field(default=0, ge=0, le=1)
    disposition: DispositionV1 | None = None


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
    if _learned(proposal.proposed_method):
        out.extend(_learned_case(proposal, facts))
    latency = facts.profile.availability_latency_hours
    if latency and not any(
        re.search(r"latenc|availab", text, re.I) for text in proposal.leakage_risks
    ):
        out.append(_finding(ReviewCode.LATENCY_NOT_NAMED, f"the data have {latency} h latency"))
    known = facts.profile.model_dump(mode="json")
    for text in unbacked_numbers(proposal.data_sufficiency, known):
        out.append(_finding(ReviewCode.UNBACKED_DATA_CLAIM, text))
    return out


def _learned(method: str) -> bool:
    return STRATEGY_OF.get(method) in LEARNED


def _learned_case(proposal: MethodProposalV1, facts: ReviewFacts) -> list[ReviewFinding]:
    """A learned method owes a same-sample simple comparison and an elevated-hour test."""
    out = []
    simple = {m for m, s in STRATEGY_OF.items() if s in ("deterministic", "statistical")}
    if "statistical" in facts.suitability.eligible():
        simple = {m for m in simple if STRATEGY_OF[m] == "statistical"}
    named = {c.method for c in proposal.candidates}
    if not (simple & named and simple & set(facts.plan.methods)):
        detail = f"{proposal.proposed_method} has no simple method in both candidates and plan"
        out.append(_finding(ReviewCode.NO_SIMPLE_COMPARISON, detail, proposal.proposed_method))
    tested = any(_ELEVATED.search(text) for text in proposal.failure_conditions)
    if facts.problem.kind == "regression" and not tested:
        detail = "no failure condition covers elevated hours"
        out.append(_finding(ReviewCode.ELEVATED_NOT_TESTED, detail, proposal.proposed_method))
    return out


def _hindsight(proposal: MethodProposalV1, facts: ReviewFacts) -> list[ReviewFinding]:
    """Hindsight data cannot stand as issue-time evidence. Naming the risk is not using it."""
    if facts.problem.horizon_hours is None:
        return []
    texts = [proposal.hypothesis, proposal.data_sufficiency, str(facts.plan.config)]
    texts += [c.suitability for c in proposal.candidates]
    if not any(_HINDSIGHT.search(text) for text in texts):
        return []
    detail = f"reanalysis fields are not known at issue time for T+{facts.problem.horizon_hours} h"
    return [_finding(ReviewCode.HINDSIGHT_AS_FORECAST, detail)]


def check_proposal(proposal: MethodProposalV1, facts: ReviewFacts) -> list[ReviewFinding]:
    """Deterministic checks. The same inputs give the same findings."""
    return [
        *_each_method(proposal, facts), *_plan_and_cost(proposal, facts), *_case(proposal, facts),
        *_hindsight(proposal, facts),
    ]  # fmt: skip


def check_recommendation(decision: DecisionRecordV1, claims: ClaimLadderV1) -> list[ReviewFinding]:
    """After evaluation. Adoption needs a shown gain, and limits must state a subgroup failure."""
    out: list[ReviewFinding] = []
    if decision.outcome not in ("adopt", "adopt_limited"):
        return out
    better, robust = claims.better_than_baseline, claims.robust_across_subgroups
    if better.state == "failed":
        out.append(_finding(ReviewCode.ADOPT_WITHOUT_GAIN, better.evidence, claims.model))
    if robust.state == "failed":
        out.append(_finding(ReviewCode.SUBGROUP_FAILURE, robust.evidence, claims.model))
    return out


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


def apply_claims(
    decision: DecisionRecordV1, claims: ClaimLadderV1
) -> tuple[DecisionRecordV1, list[ReviewFinding]]:
    """Each finding joins the limits. A blocking one holds the decision from forwarding."""
    found = check_recommendation(decision, claims)
    added = tuple(
        f"{f.code}: {f.detail}" for f in found if f.detail not in str(decision.limitations)
    )
    limits = {"limitations": (*decision.limitations, *added)}
    return decision.model_copy(update=limits), [f for f in found if f.blocking]


def eligible_methods(facts: ReviewFacts) -> list[str]:
    """Registered methods whose strategy code found eligible, by the names a critique must use."""
    open_now = facts.suitability.eligible()
    return [method for method, strategy in STRATEGY_OF.items() if strategy in open_now]


def fact_names(facts: ReviewFacts) -> frozenset[str]:
    """What a rebuttal may cite: measured fields only."""
    measured = set(type(facts.profile).model_fields) | set(
        type(facts.suitability.facts).model_fields
    )
    return frozenset(measured | {f.name for f in fields(facts) if f.name.endswith("_seconds")})


def disposition_issues(value: DispositionV1, critique: CritiqueV1, facts: ReviewFacts) -> list[str]:
    """Code decides whether an answer holds. Saying accepted or rebutted is not enough."""
    known = {"data": facts.profile.model_dump(mode="json"), "test": critique.test.threshold}
    issues = unbacked_numbers(value.response, known)
    if value.revised_case is not None:
        found = check_proposal(value.revised_case, facts)
        issues += [f"revised_case: {f.code}" for f in found if f.blocking]
        if critique.finding in {f.code for f in found}:
            issues.append(f"revised_case: {critique.finding} is still there")
        method, named = critique.competing_method, {c.method for c in value.revised_case.candidates}
        if method is not None and method not in named | {value.revised_case.proposed_method}:
            issues.append(f"revised_case: run or name {method}")
    if value.disposition == "rebutted":
        unknown = set(value.evidence_fields) - fact_names(facts)
        issues += [f"evidence_fields: {name} is not a measured fact" for name in sorted(unknown)]
        if critique.test.metric.lower() not in value.response.lower():
            issues.append(f"response: address {critique.test.metric}, the critic's metric")
    return issues


def _critique(
    seats: Seats, proposal: MethodProposalV1, findings: list[ReviewFinding], facts: ReviewFacts
) -> CritiqueV1 | None:
    """One call and its one correction. An unusable critique changes nothing."""
    sent: dict[str, Any] = {
        "proposal": proposal, "findings": findings, "metrics": facts.plan.metrics,
        "eligible_methods": eligible_methods(facts), "data": facts.profile,
    }  # fmt: skip
    try:
        return seats.propose(
            CRITIC, CRITIC_SYSTEM, sent, "submit_critique", CritiqueV1,
            lambda value: critique_issues(value, findings, facts),
        )  # fmt: skip
    except Stopped:
        return None


def _answer(
    seats: Seats, proposal: MethodProposalV1, critique: CritiqueV1, facts: ReviewFacts
) -> DispositionV1 | None:
    """One Lead response and its one correction. No answer leaves the concern open."""
    sent = {
        "case": proposal, "critique": critique, "measured_fields": sorted(fact_names(facts)),
        "data": facts.profile, "plan": facts.plan,
    }  # fmt: skip
    try:
        return seats.propose(
            LEAD, ANSWER_SYSTEM, sent, "answer_critique", DispositionV1,
            lambda value: disposition_issues(value, critique, facts),
        )  # fmt: skip
    except Stopped:
        return None


def revised_strategy(record: MethodReviewRecordV1, plan: ExperimentPlanV1) -> str | None:
    """The strategy an accepted critique moves to, when it differs from the plan's."""
    case = record.disposition.revised_case if record.disposition else None
    strategy = STRATEGY_OF.get(case.proposed_method) if case else None
    return None if strategy == plan.config.get("strategy") else strategy


def _source(seats: Seats) -> Literal["independent_model", "same_model_second_pass"]:
    """A second call on the Lead's model is another pass, not an independent mind."""
    lead, critic = seats.role(LEAD).identity_record(), seats.role(CRITIC).identity_record()
    same = (lead["provider"], lead["model"]) == (critic["provider"], critic["model"])
    return "same_model_second_pass" if same else "independent_model"


def run_review(seats: Seats, facts: ReviewFacts) -> MethodReviewRecordV1:
    """The Lead's case, then the review of that case."""
    sent = {
        "problem": facts.problem, "data": facts.profile, "suitability": facts.suitability,
        "plan": facts.plan, "estimate_seconds": facts.estimate_seconds,
    }  # fmt: skip
    proposal = seats.propose(
        LEAD, PROPOSE_SYSTEM, sent, "propose_method", MethodProposalV1, completeness
    )
    return review_case(seats, proposal, facts)


def review_case(
    seats: Seats, proposal: MethodProposalV1, facts: ReviewFacts
) -> MethodReviewRecordV1:
    """Code's findings, at most one critic call and one Lead response."""
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
    answer = _answer(seats, proposal, critique, facts) if critique else None
    open_concern = critique is not None and (
        answer is None or answer.disposition == "needs_revision"
    )
    return MethodReviewRecordV1(
        proposal=proposal, findings=tuple(findings),
        verdict="needs_revision" if open_concern else "proceed", critic_calls=1,
        critique=critique, critique_state="usable" if critique else "unusable",
        critic_source=_source(seats), lead_responses=1 if critique else 0, disposition=answer,
    )  # fmt: skip
