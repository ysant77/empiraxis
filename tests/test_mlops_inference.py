"""Batch inference refuses what the registry has not approved or the input cannot support."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from mlops_helpers import KEY, NAMES, SHA, approve, series, stored_bundle, times

from earthlab.efficiency.artifacts import ArtifactRef
from earthlab.mlops import preprocess
from earthlab.mlops.contracts import (
    FeatureArtifactV1,
    FittedPipelineV1,
    PostprocessV1,
    PredictionV1,
)
from earthlab.mlops.registry import Registry
from earthlab.mlops.serve import InputRefused, load, predict_batch, readiness
from earthlab.team.resources import OPERATOR_KEY_ENV


@pytest.fixture(autouse=True)
def operator_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, KEY)


def run(
    registry: Registry,
    ref: ArtifactRef,
    values: np.ndarray | None = None,
    columns: tuple[str, ...] = NAMES,
    allow_research: bool = False,
) -> list[PredictionV1]:
    issues = np.array([120, 121, 122])
    return predict_batch(
        registry, ref, series() if values is None else values, columns, SHA, issues,
        times(issues), allow_research,
    )  # fmt: skip


def test_an_approved_bundle_predicts_in_original_units(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    ref = registry.register(stored_bundle(registry))
    approve(registry, ref, tmp_path)
    out = run(registry, ref)
    assert [p.issue_index for p in out] == [120, 121, 122]
    assert all(p.status == "approved" and p.readiness == "validated_experimental" for p in out)
    assert all(p.output_names == NAMES and p.bundle_sha256 == ref.sha256 for p in out)
    truth = series()[[120, 121, 122]]
    np.testing.assert_allclose(np.array([p.values for p in out], dtype=float), truth, rtol=0.2)


def test_an_unregistered_bundle_is_refused(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    with pytest.raises(InputRefused, match="not registered"):
        run(registry, ArtifactRef(kind="record", sha256=SHA))


def test_a_candidate_runs_only_as_labelled_research(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    ref = registry.register(stored_bundle(registry))
    with pytest.raises(InputRefused, match="candidate"):
        run(registry, ref)
    out = run(registry, ref, allow_research=True)
    assert all(p.status == "candidate" and p.readiness == "research" for p in out)


def test_a_rejected_bundle_is_refused_even_for_research(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    ref = registry.register(stored_bundle(registry))
    report = tmp_path / "evaluation.json"
    report.write_text("{}", encoding="utf-8")
    registry.evaluate(ref, report, False)
    with pytest.raises(InputRefused, match="rejected"):
        run(registry, ref, allow_research=True)


def test_an_evaluated_bundle_is_not_approved(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    ref = registry.register(stored_bundle(registry))
    report = tmp_path / "evaluation.json"
    report.write_text("{}", encoding="utf-8")
    registry.evaluate(ref, report, True)
    with pytest.raises(InputRefused, match="evaluated"):
        run(registry, ref)


def test_no_status_or_flag_claims_production(tmp_path: Path) -> None:
    assert readiness("approved") == "validated_experimental"
    assert readiness("candidate") == readiness("rejected") == "research"
    (tmp_path / "production-evidence.json").write_text("{}", encoding="utf-8")
    with pytest.raises(InputRefused, match="production claims"):
        readiness("approved", tmp_path)
    registry = Registry(tmp_path / "r")
    ref = registry.register(stored_bundle(registry))
    approve(registry, ref, tmp_path)
    assert {p.readiness for p in run(registry, ref)} == {"validated_experimental"}


def test_a_missing_feature_stops_the_run(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    ref = registry.register(stored_bundle(registry))
    approve(registry, ref, tmp_path)
    values = series()
    values[119, 0] = np.nan  # one lag of issue 121 (offset 2)
    with pytest.raises(InputRefused, match="missing feature"):
        run(registry, ref, values)


def test_other_input_columns_are_refused(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    ref = registry.register(stored_bundle(registry))
    approve(registry, ref, tmp_path)
    with pytest.raises(InputRefused, match="differ"):
        run(registry, ref, columns=("south", "north"))


def test_a_feature_record_that_disagrees_with_its_preprocessing_is_refused(
    tmp_path: Path,
) -> None:
    registry = Registry(tmp_path / "r")
    good = stored_bundle(registry)
    feature = registry.record(good.feature, FeatureArtifactV1)
    fitted = registry.record(feature.fitted_pipeline, FittedPipelineV1)
    drifted = feature.model_copy(update={"feature_names": (*fitted.feature_names[:-1], "x")})
    bad = good.model_copy(update={"feature": registry.store.put_record(drifted)})
    ref = registry.register(bad)
    with pytest.raises(InputRefused, match="disagree"):
        run(registry, ref, allow_research=True)


def test_a_matrix_that_does_not_fit_the_schema_is_refused(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    ref = registry.register(stored_bundle(registry))
    fitted = registry.record(
        registry.record(ref_feature(registry, ref), FeatureArtifactV1).fitted_pipeline,
        FittedPipelineV1,
    )
    short = fitted.model_copy(update={"feature_names": fitted.feature_names[:-1]})
    with pytest.raises(ValueError, match="does not match"):
        preprocess.build(short, series(), np.array([50]), 200)


def ref_feature(registry: Registry, ref: ArtifactRef) -> ArtifactRef:
    return registry.bundle(ref).feature


def test_inconsistent_model_and_postprocessor_bundles_are_refused(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    good = stored_bundle(registry)
    regression_alarm = good.model_copy(update={"postprocess": PostprocessV1(alarm_cut=0.5)})
    ref = registry.register(regression_alarm)
    with pytest.raises(InputRefused, match="alarm cut"):
        load(registry, ref)
    classifier = good.model_copy(
        update={"task": "classification", "postprocess": PostprocessV1(invert_scaling=True)}
    )
    ref = registry.register(classifier)
    with pytest.raises(InputRefused, match="regression steps"):
        load(registry, ref)
    clipped = good.model_copy(
        update={"task": "classification", "postprocess": PostprocessV1(clip_nonnegative=True)}
    )
    with pytest.raises(InputRefused, match="regression steps"):
        load(registry, registry.register(clipped))


def test_a_changed_weight_file_stops_the_run(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    ref = registry.register(stored_bundle(registry))
    approve(registry, ref, tmp_path)
    blob = registry.blobs / f"{registry.bundle(ref).weights_sha256}.npz"
    blob.write_bytes(blob.read_bytes() + b"x")
    with pytest.raises(Exception, match="npz"):
        run(registry, ref)


def test_rollback_serves_the_previous_approved_bundle(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    first = registry.register(stored_bundle(registry, seed=1))
    second = registry.register(stored_bundle(registry, seed=2))
    assert registry.latest_approved("m") is None
    for ref in (first, second):
        approve(registry, ref, tmp_path)
    assert registry.latest_approved("m") == second
    previous = registry.latest_approved("m", skip=1)
    assert previous == first
    assert registry.latest_approved("m", skip=2) is None
    assert previous is not None
    assert {p.bundle_sha256 for p in run(registry, previous)} == {first.sha256}
