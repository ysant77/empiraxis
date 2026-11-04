"""Typed records of the M4.1 assessment council: evidence package, role outputs, checks.

Every model output is parsed into one of these contracts. A field that the contract does not
name fails the parse. Code, not a model, decides whether a record is valid.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict

SHA256 = r"^[0-9a-f]{64}$"
REF = r"^[A-Za-z0-9_.:-]{1,64}$"


class Availability(StrEnum):
    """When a source value can be known, relative to a forecast issue time."""

    ISSUE_TIME_VALID = "issue_time_valid"
    HINDSIGHT = "hindsight"
    UNKNOWN = "unknown"


class Decision(StrEnum):
    RETAIN_BASELINE = "retain_baseline"
    ADOPT_LIMITED = "adopt_limited"
    ADOPT = "adopt"
    REQUEST_VALIDATION = "request_validation"
    REQUEST_DATA = "request_data"
    PROCEED_WITH_LIMITS = "proceed_with_limits"
    ABSTAIN = "abstain"


class FaultClass(StrEnum):
    """Methodological fault classes. The critic and the specialists use the same list."""

    BASELINE_UNSUITABLE = "baseline_unsuitable"
    NEURAL_UNJUSTIFIED = "neural_unjustified"
    TEMPORAL_LEAKAGE = "temporal_leakage"
    HINDSIGHT_AS_FORECAST = "hindsight_as_forecast"
    UNFAIR_COMPARISON = "unfair_comparison"
    SUBGROUP_DETERIORATION = "subgroup_deterioration"
    UNSUPPORTED_CAUSALITY = "unsupported_causality"
    MISSING_OBSERVATIONS = "missing_observations"
    PROVENANCE_CONFLICT = "provenance_conflict"
    NON_INDEPENDENT_EVIDENCE = "non_independent_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NUMERIC_MISSTATEMENT = "numeric_misstatement"


class Action(StrEnum):
    EXCLUDE_INPUT = "exclude_input"
    ADD_CHECK = "add_check"
    REQUEST_DATA = "request_data"
    ABSTAIN = "abstain"
    PROCEED_WITH_LIMITS = "proceed_with_limits"
    CLARIFY = "clarify"
    REVISE_CLAIM = "revise_claim"


Severity = Literal["low", "medium", "high"]


class SourceV1(Strict):
    id: str = Field(pattern=REF)
    dataset: str
    role: Literal["observation", "estimate", "reanalysis", "derived", "evaluation"]
    availability: Availability
    latency_hours: float | None = None
    sha256: str | None = Field(default=None, pattern=SHA256)
    origin: str = Field(description="Repository path or commit and path of the artifact.")


class FactV1(Strict):
    id: str = Field(pattern=REF)
    statement: str = Field(max_length=300)
    value: float | None = None
    unit: str = ""
    source: str = Field(pattern=REF)


class EvidencePackageV1(Strict):
    """ScientificEvidencePackageV1: one immutable question and the evidence for it."""

    schema_version: Literal["1"] = "1"
    package_id: str = Field(pattern=REF)
    scenario: Literal["model_selection", "provenance", "sufficiency", "design"]
    question: str = Field(max_length=400)
    study_area: str
    interval: str
    target: str
    acceptance_criteria: list[str] = Field(min_length=1)
    sources: list[SourceV1] = Field(min_length=1)
    facts: list[FactV1] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    allowed_decisions: list[Decision] = Field(min_length=1)
    fixture: bool = Field(description="True when values are a labelled fixture, not a real run.")


class FindingV1(Strict):
    id: str = Field(pattern=REF)
    fault_class: FaultClass
    claim: str = Field(min_length=10, max_length=300)
    evidence: list[str] = Field(min_length=1, max_length=4)
    cited_values: dict[str, float] = Field(default_factory=dict)
    severity: Severity
    action: Action
    uncertainty: str = Field(max_length=200)


class DataAssessmentV1(Strict):
    examined: list[str] = Field(min_length=1)
    findings: list[FindingV1] = Field(max_length=5)
    recommended_exclusions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list, max_length=4)


class ModelAssessmentV1(Strict):
    baseline: str
    alternatives: list[str] = Field(max_length=4)
    training_justified: bool
    eligible_inputs: list[str]
    ineligible_inputs: list[str]
    split_suitable: bool
    findings: list[FindingV1] = Field(max_length=5)
    recommended_experiment: str = Field(max_length=300)
    limitations: list[str] = Field(default_factory=list, max_length=4)


class DispositionV1(Strict):
    finding_id: str = Field(pattern=REF)
    verdict: Literal["accept", "reject", "clarify"]
    reason: str = Field(min_length=5, max_length=240)
    evidence: list[str] = Field(default_factory=list, max_length=4)


class LeadPlanV1(Strict):
    dispositions: list[DispositionV1] = Field(max_length=12)
    decision: Decision
    inputs_used: list[str]
    excluded_inputs: list[str]
    plan: str = Field(min_length=20, max_length=600)
    claims: list[str] = Field(max_length=4)
    unresolved: list[str] = Field(default_factory=list, max_length=4)
    limitations: list[str] = Field(default_factory=list, max_length=4)


class CritiqueV1(Strict):
    """ScientificCritiqueV1: advisory. It sets no score, threshold, outcome or approval."""

    verdict: Literal["no_concern", "concerns"]
    findings: list[FindingV1] = Field(max_length=4)


class CritiqueV2(Strict):
    """Same fields as V1, findings first: the verdict is written after the review (Amendment 1)."""

    findings: list[FindingV1] = Field(max_length=4)
    verdict: Literal["no_concern", "concerns"]


Critique = CritiqueV1 | CritiqueV2
CRITIC_CONTRACTS: dict[str, type[CritiqueV1] | type[CritiqueV2]] = {
    "v1": CritiqueV1,
    "v2": CritiqueV2,
}


class ResponseV1(Strict):
    finding_id: str = Field(pattern=REF)
    verdict: Literal["accept", "rebut"]
    reason: str = Field(min_length=5, max_length=240)
    evidence: list[str] = Field(default_factory=list, max_length=4)


class RebuttalV1(Strict):
    responses: list[ResponseV1] = Field(max_length=4)
    decision: Decision
    inputs_used: list[str]
    excluded_inputs: list[str]
    plan: str = Field(min_length=20, max_length=600)
    claims: list[str] = Field(max_length=4)


class PMReviewV1(Strict):
    addresses_question: bool
    criteria_met: list[bool]
    action: Literal["forward", "revise", "abstain"]
    note: str = Field(min_length=5, max_length=300)


class CheckV1(Strict):
    name: str
    passed: bool
    detail: str = ""


class CheckReportV1(Strict):
    subject: str
    checks: list[CheckV1]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)
