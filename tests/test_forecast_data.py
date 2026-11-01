"""E1 data rules: the audit, the time rule, the splits and the sealed test period."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from earthlab.forecast import evaluator, samples
from earthlab.forecast.dataset import (
    EXCLUDED_LABELS,
    REGIONS,
    SPLITS,
    Audit,
    Grid,
    index_of,
    load_grid,
    parse_label,
)
from earthlab.forecast.pipeline import FeatureSpec, Workbench

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "nea" / "Historical1hrPM2.5.csv"


@pytest.fixture(scope="module")
def loaded() -> tuple[Grid, Audit]:
    return load_grid(SOURCE)


def test_the_audit_matches_the_published_file(loaded: tuple[Grid, Audit]) -> None:
    _, audit = loaded
    assert audit.grid_hours == 109584 and audit.rows == 109584
    assert audit.source_sha256.startswith("2fb76e1c")
    assert audit.duplicate_labels == 3
    assert len(audit.conflicting_labels) == 3
    assert audit.unparsed_labels == ("2016-04-04 010:00:00",)
    assert audit.excluded_labels == 8
    assert audit.longest_gap_hours == 2


def test_a_malformed_label_is_never_guessed() -> None:
    assert parse_label("2016-04-04 010:00:00") is None
    assert parse_label("4/4/2016 010:00") is None
    label = parse_label("1/4/2014 1:00")
    assert label is not None and label.month == 4 and label.day == 1


def test_excluded_labels_are_not_used_as_values(loaded: tuple[Grid, Audit]) -> None:
    grid = loaded[0]
    for label in EXCLUDED_LABELS:
        assert np.isnan(grid.values[index_of(label)]).all()


def test_nothing_is_filled(loaded: tuple[Grid, Audit]) -> None:
    assert int(np.isnan(loaded[0].values).sum()) == 8 * len(REGIONS)


def test_a_sample_stays_inside_its_split() -> None:
    for split in ("train", "validation"):
        first, last = samples.split_bounds(split)
        issues = samples.issue_times(split, 48)
        assert issues.min() >= first and issues.max() + max(samples.HORIZONS) <= last


def test_validation_inputs_may_read_train_but_targets_may_not_cross() -> None:
    issues = samples.issue_times("validation", 48)
    assert issues.min() == index_of(SPLITS["validation"][0])
    assert issues.max() + 6 == index_of(SPLITS["validation"][1])


def test_persistence_reads_nothing_after_its_availability_time(loaded: tuple[Grid, Audit]) -> None:
    grid = loaded[0]
    issues = samples.issue_times("validation", 48)[:500]
    before = samples.persistence(grid, issues)
    changed = grid.values.copy()
    for t in issues[:5]:
        changed[t - 1 :] = -999.0  # everything from T - 1 on is not yet published at T
        now = samples.persistence(Grid(changed, grid.source_sha256), np.array([t]))
        assert np.array_equal(now[0], before[int(t - issues[0])])
        changed[t - 1 :] = grid.values[t - 1 :]


@pytest.mark.parametrize(("h", "period"), [(1, 24), (6, 24), (23, 24), (24, 24), (6, 168)])
def test_naive_baselines_use_a_usable_label_at_the_right_hour(h: int, period: int) -> None:
    grid = Grid(np.arange(2000, dtype=float)[:, None].repeat(5, axis=1), "x")
    t = np.array([1000])
    value = (samples.daily_naive if period == 24 else samples.weekly_naive)(grid, t, h)[0, 0]
    assert value <= 1000 - samples.USABLE_OFFSET
    assert (1000 + h - value) % period == 0


def test_the_scaler_fits_on_train_only(loaded: tuple[Grid, Audit]) -> None:
    grid = loaded[0]
    changed = grid.values.copy()
    changed[samples.split_bounds("validation")[0] :] += 1000
    plain = samples.fit_scaler(grid, True)
    moved = samples.fit_scaler(Grid(changed, grid.source_sha256), True)
    assert np.array_equal(plain.mean, moved.mean) and np.array_equal(plain.std, moved.std)


def test_a_scaler_inverts_exactly() -> None:
    scaler = samples.Scaler(np.zeros(1), np.ones(1) * 2, True)
    assert scaler.invert(scaler.apply(np.array([7.0])))[0] == pytest.approx(7.0)


@pytest.fixture(scope="module")
def bench(tmp_path_factory: pytest.TempPathFactory) -> Workbench:
    return Workbench(tmp_path_factory.mktemp("e1"), SOURCE)


def test_the_feature_file_holds_no_test_period(bench: Workbench) -> None:
    built = bench.build_features(FeatureSpec(window=24))
    with np.load(built["path"]) as saved:
        assert saved["series"].shape[0] == samples.SEALED_FROM
        assert saved["calendar"].shape[0] == samples.SEALED_FROM
        assert saved["valid_issues"].max() + 6 < samples.SEALED_FROM
    assert built["last_visible_label"] == "2023-12-31T23:00:00"


def test_the_sensitivity_run_drops_the_2015_haze_from_train(bench: Workbench) -> None:
    built = bench.build_features(FeatureSpec(window=24, exclude_2015_haze=True))
    with np.load(built["path"]) as saved:
        issues = saved["train_issues"]
    start = index_of(parse_label("1/8/2015 0:00"))  # type: ignore[arg-type]
    end = index_of(parse_label("30/11/2015 23:00"))  # type: ignore[arg-type]
    assert not ((issues >= start) & (issues <= end)).any()


def test_baselines_are_frozen_once(bench: Workbench) -> None:
    done = bench.baselines(24)
    assert len(done) == 5
    with pytest.raises(ValueError, match="frozen"):
        bench.baselines(24)


def test_the_evaluator_rebuilds_targets_alone(bench: Workbench) -> None:
    truth, digest = evaluator.read_truth(SOURCE)
    assert digest == bench.grid.source_sha256
    assert np.array_equal(truth, bench.grid.values, equal_nan=True)
    issues = samples.issue_times("validation", 48)[:100]
    assert np.array_equal(
        evaluator.reference(truth, issues), samples.persistence(bench.grid, issues), equal_nan=True
    )


def test_the_evaluator_imports_no_training_code() -> None:
    tree = ast.parse((ROOT / "src/earthlab/forecast/evaluator.py").read_text(encoding="utf-8"))
    names = [
        node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
    ]
    assert not [n for n in names if n and n.startswith("earthlab")]


def test_metrics_match_a_hand_count() -> None:
    truth = np.full((200, 5), np.nan)
    truth[:] = 10.0
    truth[106:] = 20.0
    issues = np.array([100])
    predicted = np.full((1, 1, 5), 18.0)
    row = evaluator.evaluate(truth, issues, [6], predicted)["6"]
    assert row["all"]["mae"] == 2.0 and row["all"]["bias"] == -2.0
    assert row["mean_skill"] == pytest.approx(1 - 2 / 10)


def test_the_bootstrap_is_repeatable_and_brackets_the_value() -> None:
    rng = np.random.default_rng(1)
    target = rng.normal(20, 5, (2000, 5))
    pred, base = target + rng.normal(0, 1, target.shape), target + rng.normal(0, 2, target.shape)
    issues = np.arange(2000)
    first = evaluator.bootstrap(pred, base, target, issues)
    assert first == evaluator.bootstrap(pred, base, target, issues)
    assert first["mean_skill_low"] < 0.5 < first["mean_skill_high"]


def test_a_dataclass_spec_change_makes_a_new_feature_set(bench: Workbench) -> None:
    one = bench.build_features(FeatureSpec(window=24))
    two = bench.build_features(replace(FeatureSpec(window=24), log_transform=False))
    assert one["features_id"] != two["features_id"]
