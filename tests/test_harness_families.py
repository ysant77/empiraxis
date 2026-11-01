"""Registered methods through the existing workbench and evaluators, on a synthetic NEA file."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from earthlab.cli import main
from earthlab.digest import file_digest
from earthlab.efficiency.artifacts import ArtifactRef
from earthlab.forecast import samples as S
from earthlab.forecast.dataset import GRID_END, GRID_START, REGIONS
from earthlab.harness.families_run import RunSpec, run_classification, run_regression
from earthlab.mlops.contracts import FeatureArtifactV1
from earthlab.mlops.registry import Registry

FAST = RunSpec(
    lags=3,
    configs={
        "persistence": {}, "climatology": {}, "ridge": {"alpha": 10.0},
        "trees": {"trees": 5, "depth": 2, "rate": 0.3},
        "logistic": {"penalty": 1.0, "balanced": True},
        "trees_classifier": {"trees": 5, "depth": 2, "rate": 0.3},
    },
)  # fmt: skip


def write_source(path: Path, test_shift: float = 0.0) -> Path:
    """The published file's layout. Values are synthetic: a daily wave and a slow random walk."""
    rng = np.random.default_rng(11)
    hours = int((GRID_END - GRID_START).total_seconds() // 3600) + 1
    walk = np.zeros((hours, len(REGIONS)))
    noise = rng.normal(0, 0.2, size=walk.shape)
    for i in range(1, hours):
        walk[i] = 0.97 * walk[i - 1] + noise[i]
    wave = 0.3 * np.sin(2 * np.pi * (np.arange(hours) % 24) / 24)[:, None]
    values = np.exp(2.5 + walk + wave)
    values[S.SEALED_FROM :] += test_shift
    lines = ["time,north,south,east,west,central"]
    for i in range(hours):
        stamp = (GRID_START + timedelta(hours=i)).strftime("%d/%m/%Y %H:%M")
        lines.append(stamp + "," + ",".join(f"{v:.1f}" for v in values[i]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_source(tmp_path_factory.mktemp("nea") / "nea.csv")


@pytest.fixture(scope="module")
def regression(source: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("s1")
    return run_regression(root / "run", root / "registry", source, FAST)


def test_the_regression_methods_are_scored_beside_the_baselines(
    regression: dict[str, Any],
) -> None:
    assert set(regression["scores"]) == {
        "B0_persistence", "B1_daily_naive", "B2_weekly_naive", "B3_climatology",
        "B4_lagged_ridge", "M_persistence", "M_climatology", "M_ridge", "M_trees",
    }  # fmt: skip
    assert regression["split_scored"] == "validation" and regression["blocked"] == {}
    assert regression["quality_issues"] == []


def test_every_bundle_is_a_candidate_the_evaluator_moved_and_no_one_approved(
    regression: dict[str, Any],
) -> None:
    registry = Registry(Path(regression["registry"]))
    states = {row["model"]: row["status"] for row in regression["bundles"]}
    assert states == {
        "M_persistence": "rejected", "M_climatology": "rejected",
        "M_ridge": "evaluated", "M_trees": "evaluated",
    }  # fmt: skip
    for name in ("s1-ridge", "s1-trees"):
        assert [e["to"] for e in registry.history(name)] == ["candidate", "evaluated"]
        assert registry.latest_approved(name) is None


def test_the_feature_artifact_stops_before_the_sealed_period(
    regression: dict[str, Any],
) -> None:
    registry = Registry(Path(regression["registry"]))
    ref = ArtifactRef(kind="record", sha256=regression["bundles"][0]["bundle"])
    artifact = registry.record(registry.bundle(ref).feature, FeatureArtifactV1)
    assert artifact.last_input_index < S.SEALED_FROM
    assert artifact.train_span.last == S.split_bounds("train")[1]
    assert artifact.validation_span is not None and artifact.validation_span.last < S.SEALED_FROM
    bundle = registry.bundle(ref)
    assert bundle.evaluation_sha256 == file_digest(Path(regression["report"]))


def test_the_sealed_rows_cannot_change_a_result(regression: dict[str, Any], tmp_path: Path) -> None:
    shifted = write_source(tmp_path / "shifted.csv", test_shift=500.0)
    again = run_regression(tmp_path / "run", tmp_path / "registry", shifted, FAST)
    assert again["scores"] == regression["scores"]


def test_the_classification_scenario_scores_the_same_years_as_the_adapter(
    source: Path, tmp_path: Path
) -> None:
    done = run_classification(tmp_path / "run", tmp_path / "registry", source, FAST)
    assert set(done["scores"]) == {
        "persistence_alarm",
        "train_rate",
        "logistic",
        "trees_classifier",
    }
    assert done["split_scored"] == "validation years 2022 to 2023"
    assert done["scores"]["train_rate"]["passes"] is False
    assert {row["model"]: row["status"] for row in done["bundles"]} == {
        "logistic": "evaluated", "trees_classifier": "evaluated",
    }  # fmt: skip
    assert done["notes"] == {"logistic": [], "trees_classifier": []}


def test_too_few_positive_labels_block_the_classifiers(tmp_path: Path) -> None:
    flat = tmp_path / "flat.csv"
    lines = ["time,north,south,east,west,central"]
    hours = int((GRID_END - GRID_START).total_seconds() // 3600) + 1
    rng = np.random.default_rng(2)
    for i in range(hours):
        stamp = (GRID_START + timedelta(hours=i)).strftime("%d/%m/%Y %H:%M")
        lines.append(stamp + "," + ",".join(f"{v:.1f}" for v in 8 + rng.random(5)))
    flat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    done = run_classification(tmp_path / "run", tmp_path / "registry", flat, FAST)
    assert set(done["blocked"]) == {"logistic", "trees_classifier"}
    assert done["bundles"] == [] and set(done["scores"]) == {"persistence_alarm", "train_rate"}


def test_the_run_command_prints_the_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}

    def fake(folder: Path, registry: Path, source: Path, spec: RunSpec) -> dict[str, Any]:
        seen.update(folder=folder, registry=registry, lags=spec.lags)
        return {"scenario": "regression"}

    monkeypatch.setattr("earthlab.harness.families_run.run_regression", fake)
    args = ["mlops-run", "regression", "--out", str(tmp_path / "o"), "--lags", "6",
            "--registry", str(tmp_path / "r")]  # fmt: skip
    assert main(args) == 0
    assert seen["lags"] == 6 and seen["registry"] == tmp_path / "r"
    assert '"scenario": "regression"' in capsys.readouterr().out
