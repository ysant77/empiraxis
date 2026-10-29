"""ScienceBench scenarios and their deterministic scoring.

A scenario names the expected outcome type and either claim shapes (the verifier computes
every value) or the reason codes an abstention must give. Nothing here stores a numeric
answer. Arms are scored only on what they produced: status, supported claims, declared
reasons. Blocked scenarios are listed and never scored.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import Field, model_validator

from earthlab.agent.area_findings import AreaQuantity, AreaVerification
from earthlab.agent.limitations import ReasonCode
from earthlab.contracts import Region, Strict, to_sgt
from earthlab.science.burned_area import QaPolicy
from earthlab.verify.claims import ClaimKind, Verdict, VerificationResult

Expected = Literal["verified_claims", "abstain", "needs_input"]


class BenchRequirement(Strict):
    """A claim shape. 'within' accepts any claim window inside [start, end)."""

    kind: ClaimKind
    start: datetime
    end: datetime
    region: Region | None = None
    threshold: float | None = None
    match: Literal["exact", "within"] = "exact"

    def met_by(self, result: VerificationResult) -> bool:
        claim = result.claim
        if result.verdict is not Verdict.SUPPORTED or claim.kind is not self.kind:
            return False
        if self.region is not None and claim.region is not self.region:
            return False
        if self.threshold is not None and claim.threshold != self.threshold:
            return False
        start, end = to_sgt(self.start), to_sgt(self.end)
        if self.match == "exact":
            return claim.start == start and claim.end == end
        return start <= claim.start and claim.end <= end


class AreaRequirement(Strict):
    """A supported burned-area claim for this case, month, quantity and QA policy."""

    case_id: str
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    quantity: AreaQuantity = AreaQuantity.BURNED_AREA_HA
    qa_policy: QaPolicy = QaPolicy.PRIMARY

    def met_by(self, result: AreaVerification) -> bool:
        c = result.claim
        wanted = (self.case_id, self.month, self.quantity, self.qa_policy)
        return (
            result.verdict is Verdict.SUPPORTED
            and (
                c.case_id,
                c.month,
                c.quantity,
                c.qa_policy,
            )
            == wanted
        )


class Scenario(Strict):
    id: str = Field(pattern=r"^(SB|HO)-\d{2}[a-z]?$")
    priority: Literal["P0", "P1", "P2"]
    title: str
    status: Literal["ready", "blocked_unrun"]
    blocked_reason: str | None = None
    question: str = Field(min_length=10)
    expected: Expected
    requirements: list[BenchRequirement] = Field(default_factory=list)
    area_requirements: list[AreaRequirement] = Field(default_factory=list)
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    claims_allowed: bool = False

    @model_validator(mode="after")
    def _scorable(self) -> Self:
        if self.status == "blocked_unrun":
            if not self.blocked_reason:
                raise ValueError(f"{self.id}: a blocked scenario needs blocked_reason")
            return self
        if self.expected == "verified_claims" and not (self.requirements or self.area_requirements):
            raise ValueError(f"{self.id}: verified_claims needs requirements")
        if self.expected != "verified_claims" and not self.reason_codes:
            raise ValueError(f"{self.id}: an abstention needs reason_codes")
        return self


def load_scenarios(path: Path) -> list[Scenario]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    scenarios = [Scenario.model_validate(item) for item in raw["scenarios"]]
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("scenario IDs must be unique")
    return scenarios


class Outcome(Strict):
    """What one arm produced for one scenario, in arm-independent terms."""

    status: str
    supported: list[VerificationResult] = Field(default_factory=list)
    area_supported: list[AreaVerification] = Field(default_factory=list)
    rejected_claims: int = 0
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    answer_issues: list[str] = Field(default_factory=list)
    seconds: float = Field(
        ge=0, description="Wall-clock seconds for the whole arm call, failures included."
    )
    turns: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_calls: int = 0
    provider_errors: int = 0
    rejected_tool_calls: int = 0
    guard_blocks: int = 0
    cost_usd: float | None = Field(
        default=0.0, description="None when the price or the usage is not known; never guessed."
    )
    interventions: list[str] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)


class ScenarioScore(Strict):
    scenario_id: str
    arm: str
    repeat: int
    passed: bool
    false_verified: int = Field(
        description="Supported claims or a verified status the scenario rules out."
    )
    reasons: list[str]


def score(scenario: Scenario, arm: str, repeat: int, outcome: Outcome) -> ScenarioScore:
    reasons: list[str] = []
    codes = set(outcome.reason_codes)
    false_verified = 0
    if scenario.expected == "verified_claims":
        missing = [
            r for r in scenario.requirements if not any(r.met_by(s) for s in outcome.supported)
        ]
        if outcome.status != "verified":
            reasons.append(f"status {outcome.status}, expected verified")
        reasons += [
            f"requirement not met: {r.kind.value} {r.region or ''}".strip() for r in missing
        ]
        reasons += [
            f"area requirement not met: {a.case_id} {a.month} {a.quantity.value} "
            f"(QA {a.qa_policy.value})"
            for a in scenario.area_requirements
            if not any(a.met_by(s) for s in outcome.area_supported)
        ]
    else:
        if outcome.status != "abstained":
            reasons.append(f"status {outcome.status}, expected abstained")
        if outcome.status in ("verified", "partial"):
            false_verified += 1
        absent = [c.value for c in scenario.reason_codes if c not in codes]
        if absent:
            reasons.append(f"missing reason codes: {', '.join(absent)}")
        made = len(outcome.supported) + len(outcome.area_supported)
        if made and not scenario.claims_allowed:
            false_verified += made
            reasons.append(f"{made} claims where none should be made")
    return ScenarioScore(
        scenario_id=scenario.id,
        arm=arm,
        repeat=repeat,
        passed=not reasons,
        false_verified=false_verified,
        reasons=reasons,
    )
