"""Versioned records of one experiment. A model proposes inside these; code validates.

Extra fields are refused, so no proposal can carry code, a pass mark or an approval. These
records hold what the problem-specific E1 records and the delegation ticket cannot: any
problem kind, any specialist, and any artifact. E1's own records stay as they are.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.workflow.contracts import SHA256, TASK_ID

ProblemKind = Literal["regression", "classification", "raster_method"]
Method = Literal[
    "persistence", "naive", "climatology", "ridge", "logistic", "gru", "tcn",
    "raster_deterministic", "segmentation_pretrained",
]  # fmt: skip
Outcome = Literal["adopt", "adopt_limited", "retain_baseline", "abstain", "request_resource"]
HumanStatus = Literal["pending", "approved", "denied", "expired", "not_required"]
ConfigValue = int | float | bool | str


class ResearchRequestV1(Strict):
    schema_version: Literal["1"] = "1"
    request_id: str = Field(pattern=TASK_ID)
    objective: str = Field(min_length=5, max_length=500)
    constraints: tuple[str, ...] = Field(default=(), max_length=10)


class ProblemSpecV1(Strict):
    schema_version: Literal["1"] = "1"
    problem_id: str = Field(pattern=TASK_ID)
    kind: ProblemKind
    variable: str = Field(max_length=60)
    unit: str = Field(max_length=20)
    domain: str = Field(max_length=120)
    target: str = Field(max_length=200)
    horizon_hours: int | None = Field(default=None, ge=1, le=72)
    threshold: float | None = Field(default=None, gt=0)
    permitted_evidence: tuple[str, ...] = Field(min_length=1, max_length=8)
    success_criteria: tuple[str, ...] = Field(min_length=1, max_length=8)


class SourceRef(Strict):
    name: str = Field(max_length=120)
    sha256: str = Field(pattern=SHA256)


class DatasetProfileV1(Strict):
    """Facts measured by code from the source. A model never writes this record."""

    schema_version: Literal["1"] = "1"
    sources: tuple[SourceRef, ...]
    variable: str
    unit: str
    first_label: str | None = None
    last_label: str | None = None
    usable_rows: int = Field(ge=0)
    missing_fraction: float = Field(ge=0, le=1)
    labels_present: bool
    label_provenance: str = ""
    granularity: str
    resolution_m: float | None = None
    bands: tuple[str, ...] = ()
    availability_latency_hours: int = Field(default=0, ge=0)
    positive_rate: float | None = Field(default=None, ge=0, le=1)
    leakage_risks: tuple[str, ...] = ()


class MethodOption(Strict):
    method: str = Field(max_length=40)  # checked against the registry, so refusal is typed
    suitability: str = Field(min_length=5, max_length=200)


class MethodProposalV1(Strict):
    schema_version: Literal["1"] = "1"
    simplest_baseline: Method
    candidates: tuple[MethodOption, ...] = Field(min_length=1, max_length=4)
    reason: str = Field(min_length=5, max_length=400)


class BudgetV1(Strict):
    max_seconds: float = Field(gt=0)
    max_training_seconds: float = Field(ge=0)
    max_model_calls: int = Field(ge=0)


class ExperimentPlanV1(Strict):
    schema_version: Literal["1"] = "1"
    plan_id: str = Field(pattern=TASK_ID)
    methods: tuple[str, ...] = Field(min_length=1, max_length=8)
    config: dict[str, ConfigValue] = Field(default_factory=dict)
    split_protocol: str = Field(max_length=120)
    metrics: tuple[str, ...] = Field(min_length=1, max_length=12)
    input_offset_hours: int = Field(default=0, ge=-48, le=48)  # newest input is T - offset
    budget: BudgetV1
    seed: int
    decided_by: Literal["preset", "model"] = "preset"


class SpecialistTaskV1(Strict):
    """Bounds one worker. The controller writes it; the worker cannot widen it."""

    schema_version: Literal["1"] = "1"
    task_id: str = Field(pattern=TASK_ID)
    parent_task_id: str = Field(pattern=TASK_ID)
    owner: Literal["data_specialist", "ml_engineer", "software_engineer"]
    objective: str = Field(min_length=5, max_length=300)
    allowed_tools: tuple[str, ...] = Field(min_length=1)
    input_artifacts: tuple[str, ...] = ()
    acceptance_checks: tuple[str, ...] = Field(min_length=1)
    deadline_utc: datetime


class ExecutionRecord(Strict):
    """Provenance of one execution."""

    adapter: str
    seed: int
    wall_seconds: float = Field(ge=0)
    peak_rss_mb: float = Field(default=0.0, ge=0)
    code_sha256: str = Field(pattern=SHA256)
    environment: str
    log_sha256: str | None = Field(default=None, pattern=SHA256)


class ExperimentArtifactV1(Strict):
    schema_version: Literal["1"] = "1"
    artifact_id: str = Field(pattern=TASK_ID)
    task_id: str = Field(pattern=TASK_ID)
    run_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,80}$")
    kind: Literal["predictions", "model", "output", "profile"]
    file: str = Field(max_length=200)
    sha256: str = Field(pattern=SHA256)
    source_sha256: tuple[str, ...] = Field(min_length=1)
    execution: ExecutionRecord


class ModelScore(Strict):
    model: str
    metrics: dict[str, float | None]
    low: float | None = None
    high: float | None = None
    subgroups: dict[str, dict[str, float | None]] = Field(default_factory=dict)
    passes: bool
    reasons: tuple[str, ...] = ()


class EvaluationReportV1(Strict):
    """Only the independent evaluator writes this record."""

    schema_version: Literal["1"] = "1"
    evaluator: str
    evaluator_sha256: str = Field(pattern=SHA256)
    split_scored: str
    reference: str
    scores: tuple[ModelScore, ...]
    failures: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class DecisionRecordV1(Strict):
    schema_version: Literal["1"] = "1"
    outcome: Outcome
    selected: str | None = None
    rejected: tuple[str, ...] = ()
    evidence_sha256: tuple[str, ...] = ()
    reason: str = Field(min_length=5, max_length=500)
    limitations: tuple[str, ...] = ()
    human_status: HumanStatus = "pending"
