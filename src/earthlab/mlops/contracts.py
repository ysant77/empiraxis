"""Versioned records for data quality, features, model bundles and predictions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from earthlab.contracts import Strict
from earthlab.efficiency.artifacts import SHA256, ArtifactRef

Status = Literal["candidate", "evaluated", "approved", "rejected"]
Family = Literal[
    "deterministic", "traditional_ml", "hybrid", "end_to_end_dl", "transfer", "distillation"
]
Readiness = Literal["research", "validated_experimental", "deployed_production"]
Sha = Annotated[str, Field(pattern=SHA256)]


class ColumnRule(Strict):
    name: str
    unit: str
    low: float | None = None
    high: float | None = None


class DatasetSchemaV1(Strict):
    schema_version: Literal["1"] = "1"
    dataset_id: str
    cadence_hours: int = Field(ge=1)
    columns: tuple[ColumnRule, ...] = Field(min_length=1)
    min_coverage: float = Field(ge=0.0, le=1.0)


class ColumnQuality(Strict):
    name: str
    missing: int
    below_range: int
    above_range: int
    coverage: float


class QualityReportV1(Strict):
    """Facts only. The report changes no value and fills no gap."""

    schema_version: Literal["1"] = "1"
    dataset_id: str
    source_sha256: Sha
    rows: int
    first_index: int
    last_index: int
    duplicate_stamps: int
    out_of_order: int
    missing_stamps: int
    columns: tuple[ColumnQuality, ...]
    issues: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


class Log1p(Strict):
    kind: Literal["log1p"] = "log1p"


class Standardize(Strict):
    kind: Literal["standardize"] = "standardize"


Step = Annotated[Log1p | Standardize, Field(discriminator="kind")]


class Span(Strict):
    """Inclusive row positions on the source grid."""

    first: int = Field(ge=0)
    last: int

    @model_validator(mode="after")
    def _ordered(self) -> Span:
        if self.last < self.first:
            raise ValueError("a span must end after it starts")
        return self


class PipelineConfigV1(Strict):
    """What a specialist may propose. Code validates it and runs it."""

    schema_version: Literal["1"] = "1"
    steps: tuple[Step, ...] = (Log1p(), Standardize())
    lags: int = Field(default=24, ge=1, le=168)
    calendar: bool = True
    availability_offset_hours: int = Field(ge=1)
    missing: Literal["drop_row", "mask"] = "drop_row"
    cadence_hours: int = Field(default=1, ge=1)


class FittedPipelineV1(Strict):
    schema_version: Literal["1"] = "1"
    config: PipelineConfigV1
    source_sha256: Sha
    columns: tuple[str, ...]
    fit_span: Span
    fit_rows: int
    means: tuple[float, ...]
    stds: tuple[float, ...]
    feature_names: tuple[str, ...]


class FeatureArtifactV1(Strict):
    schema_version: Literal["1"] = "1"
    fitted_pipeline: ArtifactRef
    source_sha256: Sha
    train_span: Span
    validation_span: Span | None
    feature_names: tuple[str, ...]
    availability_offset_hours: int
    last_input_index: int
    rows: int
    dropped_rows: int
    code_revision: str
    matrix_sha256: Sha


class ModelCardV1(Strict):
    intended_use: str
    limitations: tuple[str, ...] = Field(min_length=1)
    not_for: tuple[str, ...] = ("Health, safety or hazard-warning decisions.",)


class PostprocessV1(Strict):
    """Declared before scoring. The evaluator scores the output of these steps."""

    schema_version: Literal["1"] = "1"
    invert_scaling: bool = False
    clip_nonnegative: bool = False
    alarm_cut: float | None = Field(default=None, gt=0.0, lt=1.0)
    calibration: tuple[float, float] | None = None  # slope and intercept, on the log odds


class EnvironmentV1(Strict):
    python: str
    packages: tuple[tuple[str, str], ...]


class ModelBundleV1(Strict):
    """Immutable. A status is an event in the registry, never a field in this record."""

    schema_version: Literal["1"] = "1"
    model_name: str
    method_id: str
    family: Family
    task: Literal["regression", "classification"]
    config: dict[str, float | int | str | bool]
    weights_sha256: Sha
    weights_format: Literal["npz"] = "npz"
    feature: ArtifactRef
    postprocess: PostprocessV1
    output_names: tuple[str, ...]
    seed: int
    environment: EnvironmentV1
    training_metrics: dict[str, float]
    subgroups: dict[str, float] = Field(default_factory=dict)
    evaluation_sha256: Sha | None = None
    card: ModelCardV1
    code_revision: str
    encoder: ArtifactRef | None = None

    @model_validator(mode="after")
    def _encoder_matches_family(self) -> ModelBundleV1:
        if (self.family == "hybrid") != (self.encoder is not None):
            raise ValueError("a hybrid bundle names its frozen encoder and no other bundle does")
        return self


class TrialV1(Strict):
    trial: int
    config: dict[str, float | int | str | bool]
    seed: int
    state: Literal["completed", "failed", "interrupted", "not_started"]
    validation_score: float | None = None
    seconds: float | None = None
    note: str = ""


class SearchSpaceV1(Strict):
    schema_version: Literal["1"] = "1"
    method_id: str
    metric: str
    direction: Literal["minimize", "maximize"]
    candidates: tuple[dict[str, float | int | str | bool], ...] = Field(min_length=1, max_length=6)
    seeds: tuple[int, ...] = Field(min_length=1, max_length=3)
    budget_seconds: float = Field(gt=0.0)
    max_memory_mb: float = Field(gt=0.0)


class SearchResultV1(Strict):
    schema_version: Literal["1"] = "1"
    space_sha256: Sha
    selection_split: Literal["validation"] = "validation"
    trials: tuple[TrialV1, ...]
    best_trial: int | None
    stopped: Literal["finished", "budget", "interrupted"]


class PredictionV1(Strict):
    schema_version: Literal["1"] = "1"
    bundle_sha256: Sha
    status: Status
    readiness: Readiness
    issue_index: int
    values: tuple[float | None, ...]
    output_names: tuple[str, ...]
    warnings: tuple[str, ...]
    source_sha256: Sha
    seconds: float
