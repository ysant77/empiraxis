"""Shared builders for the MLOps tests: a small series, a fitted pipeline and a stored bundle."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from earthlab.efficiency.artifacts import ArtifactRef
from earthlab.harness.contracts import EvaluationReportV1, ModelScore
from earthlab.mlops import families, preprocess
from earthlab.mlops.contracts import (
    EnvironmentV1,
    FeatureArtifactV1,
    ModelBundleV1,
    ModelCardV1,
    PipelineConfigV1,
    PostprocessV1,
    Span,
)
from earthlab.mlops.evidence import EvaluationRecordV1
from earthlab.mlops.registry import Registry
from earthlab.team.resources import ResourceApprovalV1, sign

SHA = "a" * 64
KEY = "operator-test-key-value"
NAMES = ("north", "south")
CONFIG = PipelineConfigV1(lags=3, calendar=False, availability_offset_hours=2)
ISSUES = np.arange(10, 150)
EVALUATOR = "earthlab.forecast.evaluator"
REPORT = EvaluationReportV1(
    evaluator=EVALUATOR, evaluator_sha256="b" * 64, split_scored="validation", reference="base",
    scores=(
        ModelScore(model="good", metrics={}, passes=True),
        ModelScore(model="bad", metrics={}, passes=False, reasons=("worse than the base",)),
    ),
).model_dump_json()  # fmt: skip
REPORT_SHA = hashlib.sha256(REPORT.encode()).hexdigest()


def series(rows: int = 200) -> np.ndarray:
    wave = np.arange(rows) % 7.0
    return np.stack([10 + wave, 20 + 2 * wave + np.arange(rows) % 5.0], axis=1)


def times(issues: np.ndarray) -> list[datetime]:
    return [datetime(2020, 1, 1) + timedelta(hours=int(i)) for i in issues]


def stored_bundle(registry: Registry, name: str = "m", seed: int = 1) -> ModelBundleV1:
    """A ridge bundle trained on the first 100 rows, with its feature record in the registry."""
    values = series()
    fitted = preprocess.fit(CONFIG, values, NAMES, Span(first=0, last=99), 99, SHA)
    built = preprocess.build(fitted, values, ISSUES, 200)
    target = preprocess.scale(fitted, values)[built.issues]
    state = families.train("ridge", "regression", built.x, target, {"alpha": 1.0}, seed)
    artifact = FeatureArtifactV1(
        fitted_pipeline=registry.store.put_record(fitted), source_sha256=SHA,
        train_span=Span(first=0, last=99), validation_span=Span(first=100, last=149),
        feature_names=fitted.feature_names, availability_offset_hours=2, last_input_index=147,
        rows=len(built.x), dropped_rows=0, code_revision="abc",
        matrix_sha256=registry.put_arrays({"x": built.x}),
    )  # fmt: skip
    return ModelBundleV1(
        model_name=name, method_id="ridge", family="deterministic", task="regression",
        config={"alpha": 1.0}, weights_sha256=registry.put_arrays(state),
        feature=registry.put_feature(fitted, artifact),
        postprocess=PostprocessV1(invert_scaling=True), output_names=NAMES, seed=seed,
        environment=EnvironmentV1(python="3.12", packages=(("numpy", "2"),)),
        training_metrics={"mae": 1.0}, evaluation_sha256=REPORT_SHA,
        card=ModelCardV1(intended_use="research", limitations=("Historical only.",)),
        code_revision="abc",
    )  # fmt: skip


def approval(ref: ArtifactRef, approved: bool = True) -> ResourceApprovalV1:
    body = ResourceApprovalV1(
        request_id="m", request_sha256=ref.sha256, approved=approved, approver="owner",
        decided_at_utc=datetime.now(UTC),
    )  # fmt: skip
    return body.model_copy(update={"signature": sign(body, KEY)})


def report_file(folder: Path) -> Path:
    path = folder / "evaluation-report.json"
    path.write_text(REPORT, encoding="utf-8")
    return path


def record(ref: ArtifactRef, registry: Registry, passed: bool = True) -> EvaluationRecordV1:
    """A record that agrees with the saved report, as the evaluator's code would write it."""
    bundle = registry.bundle(ref)
    return EvaluationRecordV1(
        bundle_sha256=ref.sha256, model_row="good" if passed else "bad", evaluator=EVALUATOR,
        evaluator_sha256="b" * 64, protocol_sha256="c" * 64, report_sha256=REPORT_SHA,
        source_sha256=SHA, feature_sha256=bundle.feature.sha256, predictions_sha256="d" * 64,
        split_scored="validation", reference="base", reproduction="exact", passes=passed,
        reasons=() if passed else ("worse than the base",), metrics={},
    )  # fmt: skip


def evaluate(registry: Registry, ref: ArtifactRef, folder: Path, passed: bool = True) -> str:
    return registry.evaluate(ref, record(ref, registry, passed), report_file(folder))


def approve(registry: Registry, ref: ArtifactRef, folder: Path) -> None:
    """Move a candidate through the evaluator and the signed human record."""
    evaluate(registry, ref, folder)
    registry.decide(ref, approval(ref), KEY)
