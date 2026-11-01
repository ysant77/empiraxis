"""Data validation, train-only preprocessing, feature records and the model registry."""

from __future__ import annotations

import pickle
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from earthlab.efficiency.artifacts import (
    ArtifactIntegrityError,
    ArtifactRef,
    MissingArtifactError,
)
from earthlab.mlops import preprocess
from earthlab.mlops.contracts import (
    ColumnRule,
    DatasetSchemaV1,
    EnvironmentV1,
    FeatureArtifactV1,
    Log1p,
    ModelBundleV1,
    ModelCardV1,
    PipelineConfigV1,
    PostprocessV1,
    SearchSpaceV1,
    Span,
    Standardize,
)
from earthlab.mlops.quality import validate
from earthlab.mlops.registry import (
    IllegalStatus,
    Registry,
    UnsafeArtifact,
    load_arrays,
    save_arrays,
)
from earthlab.team.resources import OPERATOR_KEY_ENV, ResourceApprovalV1, sign

SHA = "a" * 64
KEY = "operator-test-key-value"
SCHEMA = DatasetSchemaV1(
    dataset_id="pm", cadence_hours=1, min_coverage=0.9,
    columns=(ColumnRule(name="north", unit="ug/m3", low=0, high=500),
             ColumnRule(name="south", unit="ug/m3", low=0, high=500)),
)  # fmt: skip
NAMES, UNITS = ("north", "south"), ("ug/m3", "ug/m3")
CONFIG = PipelineConfigV1(lags=3, calendar=False, availability_offset_hours=2)


def series(rows: int = 200) -> np.ndarray:
    return np.stack([10 + np.arange(rows) % 7.0, 20 + np.arange(rows) % 5.0], axis=1)


def times(issues: np.ndarray) -> list[datetime]:
    return [datetime(2020, 1, 1) + timedelta(hours=int(i)) for i in issues]


def test_quality_reports_each_problem_and_changes_nothing() -> None:
    values = series(10)
    values[2, 0] = np.nan
    values[3, 1] = 900.0
    before = values.copy()
    stamps = np.array([0, 1, 2, 3, 3, 5, 6, 8, 7, 9])
    report = validate(SCHEMA, stamps, values, NAMES, UNITS, SHA)
    assert report.duplicate_stamps == 1 and report.out_of_order == 1
    assert report.missing_stamps == 1 and report.columns[0].missing == 1
    assert report.columns[1].above_range == 1 and not report.passed
    np.testing.assert_array_equal(values, before)


def test_quality_refuses_the_wrong_unit_or_columns() -> None:
    report = validate(SCHEMA, np.arange(4), series(4), NAMES, ("ppb", "ppb"), SHA)
    assert "units" in report.issues[0]
    report = validate(SCHEMA, np.arange(4), series(4), ("a", "b"), UNITS, SHA)
    assert "columns" in report.issues[0]


def test_low_coverage_fails_quality() -> None:
    values = series(10)
    values[:5, 1] = np.nan
    report = validate(SCHEMA, np.arange(10), values, NAMES, UNITS, SHA)
    assert any("coverage" in issue for issue in report.issues)


def test_preprocessing_cannot_fit_past_the_train_end() -> None:
    with pytest.raises(preprocess.LeakageRefused, match="past the train end"):
        preprocess.fit(CONFIG, series(), NAMES, Span(first=0, last=150), 99, SHA)


def test_fitted_state_ignores_every_later_row() -> None:
    late = series()
    late[100:] = 400.0
    first = preprocess.fit(CONFIG, series(), NAMES, Span(first=0, last=99), 99, SHA)
    second = preprocess.fit(CONFIG, late, NAMES, Span(first=0, last=99), 99, SHA)
    assert first == second


def test_inputs_stop_at_the_availability_offset() -> None:
    fitted = preprocess.fit(CONFIG, series(), NAMES, Span(first=0, last=99), 99, SHA)
    issues = np.array([50])
    base = preprocess.build(fitted, series(), issues, 200)
    changed = series()
    changed[49:] = 300.0  # issue minus one is not yet available
    same = preprocess.build(fitted, changed, issues, 200)
    np.testing.assert_array_equal(base.x, same.x)
    changed[48] = 300.0
    assert not np.array_equal(base.x, preprocess.build(fitted, changed, issues, 200).x)


def test_features_refuse_the_sealed_rows() -> None:
    fitted = preprocess.fit(CONFIG, series(), NAMES, Span(first=0, last=99), 99, SHA)
    with pytest.raises(preprocess.LeakageRefused, match="sealed"):
        preprocess.build(fitted, series(), np.array([150]), 140)


def test_a_missing_input_is_counted_and_never_filled_silently() -> None:
    values = series()
    values[60, 0] = np.nan
    fitted = preprocess.fit(CONFIG, values, NAMES, Span(first=0, last=99), 99, SHA)
    issues = np.arange(70, 76)
    dropped = preprocess.build(fitted, values, issues, 200)
    assert dropped.dropped == 0
    issues = np.arange(60, 66)
    dropped = preprocess.build(fitted, values, issues, 200)
    assert dropped.dropped == 3 and len(dropped.x) == 3


def test_mask_mode_declares_each_filled_input() -> None:
    config = CONFIG.model_copy(update={"missing": "mask"})
    values = series()
    values[60, 0] = np.nan
    fitted = preprocess.fit(config, values, NAMES, Span(first=0, last=99), 99, SHA)
    out = preprocess.build(fitted, values, np.array([62]), 200)
    assert out.dropped == 0 and out.x[0, 0] == 0.0 and out.x[0, 6] == 0.0 and out.x[0, 7] == 1.0
    assert out.names[6] == "north_lag0_known"


def test_calendar_features_need_times_and_match_the_schema() -> None:
    config = CONFIG.model_copy(update={"calendar": True})
    fitted = preprocess.fit(config, series(), NAMES, Span(first=0, last=99), 99, SHA)
    issues = np.array([50, 51])
    with pytest.raises(ValueError, match="issue times"):
        preprocess.build(fitted, series(), issues, 200)
    built = preprocess.build(fitted, series(), issues, 200, times(issues))
    assert built.x.shape[1] == len(fitted.feature_names)


def test_scaling_inverts_to_original_units() -> None:
    fitted = preprocess.fit(CONFIG, series(), NAMES, Span(first=0, last=99), 99, SHA)
    np.testing.assert_allclose(
        preprocess.invert(fitted, preprocess.scale(fitted, series())), series()
    )


def test_a_constant_train_column_is_refused() -> None:
    values = series()
    values[:, 1] = 5.0
    with pytest.raises(ValueError, match="no variation"):
        preprocess.fit(CONFIG, values, NAMES, Span(first=0, last=99), 99, SHA)


def test_a_config_with_unknown_fields_or_values_is_refused() -> None:
    with pytest.raises(ValidationError):
        PipelineConfigV1(availability_offset_hours=0)
    with pytest.raises(ValidationError):
        PipelineConfigV1.model_validate({"availability_offset_hours": 2, "code": "x"})
    assert PipelineConfigV1(availability_offset_hours=2).steps == (Log1p(), Standardize())


def test_a_search_space_is_finite_and_small() -> None:
    with pytest.raises(ValidationError):
        SearchSpaceV1(
            method_id="ridge", metric="mae", direction="minimize", seeds=(1,),
            candidates=tuple({"alpha": float(i)} for i in range(7)),
            budget_seconds=10, max_memory_mb=100,
        )  # fmt: skip


def stored_feature(registry: Registry) -> ArtifactRef:
    fitted = preprocess.fit(CONFIG, series(), NAMES, Span(first=0, last=99), 99, SHA)
    matrix = registry.put_arrays({"x": np.zeros((2, 6))})
    artifact = FeatureArtifactV1(
        fitted_pipeline=registry.store.put_record(fitted), source_sha256=SHA,
        train_span=Span(first=0, last=99), validation_span=None,
        feature_names=fitted.feature_names, availability_offset_hours=2, last_input_index=48,
        rows=2, dropped_rows=0, code_revision="abc", matrix_sha256=matrix,
    )  # fmt: skip
    return registry.put_feature(fitted, artifact)


def bundle(registry: Registry, name: str = "m", seed: int = 1) -> ModelBundleV1:
    return ModelBundleV1(
        model_name=name, method_id="ridge", family="deterministic", task="regression",
        config={"alpha": 1.0}, weights_sha256=registry.put_arrays({"w": np.ones(3)}),
        feature=stored_feature(registry), postprocess=PostprocessV1(), output_names=("north",),
        seed=seed, environment=EnvironmentV1(python="3.12", packages=(("numpy", "2"),)),
        training_metrics={"mae": 1.0},
        card=ModelCardV1(intended_use="research", limitations=("Historical only.",)),
        code_revision="abc",
    )  # fmt: skip


def approval(ref: ArtifactRef, approved: bool, key: str = KEY) -> ResourceApprovalV1:
    body = ResourceApprovalV1(
        request_id="m", request_sha256=ref.sha256, approved=approved, approver="owner",
        decided_at_utc=datetime.now(UTC),
    )  # fmt: skip
    return body.model_copy(update={"signature": sign(body, key)})


@pytest.fixture
def report(tmp_path: Path) -> Path:
    path = tmp_path / "evaluation.json"
    path.write_text("{}", encoding="utf-8")
    return path


def test_training_alone_never_approves_a_model(tmp_path: Path, report: Path) -> None:
    registry = Registry(tmp_path / "r")
    ref = registry.register(bundle(registry))
    assert registry.status(ref) == "candidate"
    with pytest.raises(IllegalStatus):
        registry.decide(ref, approval(ref, True), KEY)
    assert registry.latest_approved("m") is None


def test_only_a_signed_record_on_this_bundle_approves(
    tmp_path: Path, report: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, KEY)
    registry = Registry(tmp_path / "r")
    ref = registry.register(bundle(registry))
    other = registry.register(bundle(registry, seed=2))
    assert registry.evaluate(ref, report, True) == "evaluated"
    with pytest.raises(IllegalStatus, match="different bundle"):
        registry.decide(ref, approval(other, True), KEY)
    with pytest.raises(IllegalStatus, match="not valid"):
        registry.decide(ref, approval(ref, True, "wrong-key-value"), KEY)
    assert registry.decide(ref, approval(ref, True), KEY) == "approved"
    assert registry.latest_approved("m") == ref


def test_a_human_rejection_stands(
    tmp_path: Path, report: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, KEY)
    registry = Registry(tmp_path / "r")
    ref = registry.register(bundle(registry))
    registry.evaluate(ref, report, True)
    assert registry.decide(ref, approval(ref, False), KEY) == "rejected"
    with pytest.raises(IllegalStatus):
        registry.decide(ref, approval(ref, True), KEY)
    assert registry.latest_approved("m") is None


def test_a_failed_evaluation_rejects_the_model(tmp_path: Path, report: Path) -> None:
    registry = Registry(tmp_path / "r")
    ref = registry.register(bundle(registry))
    assert registry.evaluate(ref, report, False) == "rejected"


def test_rollback_finds_the_previous_approved_bundle(
    tmp_path: Path, report: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, KEY)
    registry = Registry(tmp_path / "r")
    refs = [registry.register(bundle(registry, seed=s)) for s in (1, 2)]
    for ref in refs:
        registry.evaluate(ref, report, True)
        registry.decide(ref, approval(ref, True), KEY)
    assert registry.latest_approved("m") == refs[1]
    assert registry.latest_approved("m", skip=1) == refs[0]


def test_a_changed_record_or_blob_is_refused(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    ref = stored_feature(registry)
    (registry.store.objects / f"{ref.sha256}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError):
        registry.record(ref, FeatureArtifactV1)
    digest = registry.put_arrays({"w": np.ones(2)})
    (registry.blobs / f"{digest}.npz").write_bytes(b"PK\x03\x04broken")
    with pytest.raises(ArtifactIntegrityError):
        registry.arrays(digest)


def test_a_missing_artifact_is_refused(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    with pytest.raises(MissingArtifactError):
        registry.arrays(SHA)
    with pytest.raises(MissingArtifactError):
        registry.record(ArtifactRef(kind="record", sha256=SHA), FeatureArtifactV1)
    with pytest.raises(MissingArtifactError):
        registry.register(bundle(registry).model_copy(update={"weights_sha256": SHA}))


def test_a_pickle_is_never_loaded(tmp_path: Path) -> None:
    class Trap:
        ran = False

        def __reduce__(self) -> tuple[object, tuple[str]]:
            return (print, ("loaded",))

    path = tmp_path / "model.pkl"
    path.write_bytes(pickle.dumps(Trap()))
    from earthlab.digest import file_digest

    with pytest.raises(UnsafeArtifact, match="not an npz"):
        load_arrays(path, file_digest(path))


def test_object_arrays_are_refused_both_ways(tmp_path: Path) -> None:
    path = tmp_path / "w.npz"
    with pytest.raises(UnsafeArtifact):
        save_arrays(path, {"w": np.array([{"a": 1}], dtype=object)})
    with path.open("wb") as out:
        np.savez(out, w=np.array([{"a": 1}], dtype=object))
    from earthlab.digest import file_digest

    with pytest.raises(UnsafeArtifact, match="objects"):
        load_arrays(path, file_digest(path))
