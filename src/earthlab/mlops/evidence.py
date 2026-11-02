"""Typed evidence from an evaluator, a bundle check, an inference run and a readiness report.

No field here is a request. Code recomputes each record from saved files. The readiness record
cannot say production-ready: its schema has no value for that claim.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.mlops.contracts import Sha, Status

TRUSTED_EVALUATORS = ("earthlab.forecast.evaluator", "earthlab.harness.eval_classify")
Reproduction = Literal["exact", "unsupported_hybrid"]
ScientificLabel = Literal[
    "hindsight_diagnostic", "simulated_availability_hindcast", "prospective_forecast"
]
Outcome = Literal["verified_experimental", "verified_approved", "refused"]
InferenceState = Literal["real_data", "synthetic_smoke", "not_run"]


class EvaluationRecordV1(Strict):
    """One model row, recomputed from the saved predictions and the published source."""

    schema_version: Literal["1"] = "1"
    bundle_sha256: Sha
    model_row: str
    evaluator: str
    evaluator_sha256: Sha
    protocol_sha256: Sha
    report_sha256: Sha
    source_sha256: Sha
    feature_sha256: Sha
    predictions_sha256: Sha
    split_scored: str
    reference: str
    reproduction: Reproduction
    passes: bool
    reasons: tuple[str, ...]
    metrics: dict[str, float | None]


class CheckV1(Strict):
    name: str
    passed: bool
    detail: str


class BundleVerificationV1(Strict):
    schema_version: Literal["1"] = "1"
    bundle_sha256: Sha
    model_name: str | None
    status: Status | None
    outcome: Outcome
    checks: tuple[CheckV1, ...]
    evaluation: EvaluationRecordV1 | None = None


class DataValidityV1(Strict):
    source_sha256: Sha | None
    pinned_source: bool
    quality_issues: tuple[str, ...]
    alignment_verdict: str
    alignment_findings: tuple[str, ...]
    valid: bool


class InferenceEvidenceV1(Strict):
    state: InferenceState
    input_sha256: Sha | None = None
    output_sha256: Sha | None = None
    rows_compared: int = Field(default=0, ge=0)
    max_abs_difference: float | None = None
    matches_reference: bool = False
    reference_mae: float | None = None
    output_mae: float | None = None
    note: str = ""


class ResourceEvidenceV1(Strict):
    """Measured on one batch command. Absent means it was not measured."""

    seconds_total: float | None = None
    seconds_per_row: float | None = None
    peak_rss_mb: float | None = None
    conditions: str = "not measured"


class HighPmEvidenceV1(Strict):
    threshold_ug_m3: float
    model_mae: float | None
    reference_mae: float | None
    model_recall: float | None
    worse_than_reference: bool


class DeploymentReadinessV1(Strict):
    schema_version: Literal["1"] = "1"
    bundle_sha256: Sha
    model_name: str | None
    scientific_label: ScientificLabel
    data: DataValidityV1
    integrity_checks: tuple[CheckV1, ...]
    verification_outcome: Outcome
    independent_evaluation: EvaluationRecordV1 | None
    inference: InferenceEvidenceV1
    high_pm25: HighPmEvidenceV1 | None
    resources: ResourceEvidenceV1
    missing_operational_evidence: tuple[str, ...] = Field(min_length=1)
    human_approval: Literal["none", "approved", "rejected"]
    readiness: Literal["research", "validated_experimental"]
    production_ready: Literal[False] = False
