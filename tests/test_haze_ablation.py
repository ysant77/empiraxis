"""The 2015 ablation: every feature is known at the issue time, and no target crosses a fold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from earthlab.forecast.dataset import load_grid
from earthlab.haze import ablation as A
from earthlab.haze import ablation_features as F

ROOT = Path(__file__).resolve().parents[1]
GRID, _ = load_grid(ROOT / "data" / "nea" / "Historical1hrPM2.5.csv")
START = datetime(2015, 9, 1, tzinfo=UTC)


def test_no_train_target_reaches_the_scored_block() -> None:
    for train, test in A.folds(F.issues()):
        assert train.max() + F.HORIZON < test.min()
        assert np.all(np.diff(test) == 1)


def test_pm25_lags_end_two_hours_before_the_issue() -> None:
    row = F.issues()[:1]
    lags = F.pm25_lags(GRID, row, 0)
    assert lags[0, 0] == GRID.values[row[0] - 2, 0] or np.isnan(lags[0, 0])
    assert lags.shape == (1, F.LAGS)


def test_met_features_ignore_the_issue_hour_and_later() -> None:
    rows = F.issues()[:3]
    met = {f"{b}/{lv}/{k}": np.arange(1464, dtype=float)
           for b in F.BOXES for lv in F.LEVELS for k in ("u_ms", "v_ms", "precip_mm")}  # fmt: skip
    before = F.met_features(rows, START, met)
    at = int((F.utc_of(int(rows[-1])) - START).total_seconds() // 3600)
    changed = {k: np.where(np.arange(1464) >= at, -99.0, v) for k, v in met.items()}
    assert np.array_equal(before[-1], F.met_features(rows, START, changed)[-1])


def test_a_fire_counts_only_three_hours_after_its_pass() -> None:
    row = F.issues()[100:101]
    issue = F.utc_of(int(row[0]))
    times = [issue - timedelta(hours=2), issue - timedelta(hours=4), issue - timedelta(hours=30)]
    firms = {}
    for box in F.BOXES:
        firms[f"{box}/t"] = np.array(sorted(t.timestamp() for t in times))
        firms[f"{box}/frp"] = np.ones(3)
    counts = F.fire_features(row, firms)[0]
    assert list(counts[:3]) == [1.0, 2.0, 1.0]  # 24 h, 72 h, FRP in 24 h for box a


def test_paired_skill_is_zero_for_identical_errors() -> None:
    err = np.array([1.0, -2.0, 3.0, -1.0])
    out = A.paired(err, err, np.array(["d1", "d1", "d2", "d2"]))
    assert out == {"skill": 0.0, "low": 0.0, "high": 0.0}


def test_the_inner_scaler_ignores_the_inner_holdout() -> None:
    rows = np.arange(200, dtype=np.int64)
    x = np.random.default_rng(0).normal(size=(200, 3))
    x_in, _, _, held = A.inner_split(x, rows)
    shifted = x.copy()
    shifted[held] += 1000.0
    again, x_held, _, _ = A.inner_split(shifted, rows)
    assert np.array_equal(x_in, again)
    assert x_held.mean() > 100  # the holdout is scaled with inner-train statistics only


def test_a_fire_window_holds_exactly_its_hours_of_visible_passes() -> None:
    row = F.issues()[100:101]
    issue = F.utc_of(int(row[0]))
    minute = timedelta(minutes=1)
    inside = [issue - timedelta(hours=3), issue - timedelta(hours=27) + minute]
    outside = [issue - timedelta(hours=3) + minute, issue - timedelta(hours=27)]
    times = sorted(t.timestamp() for t in inside + outside)
    firms = {}
    for box in F.BOXES:
        firms[f"{box}/t"] = np.array(times)
        firms[f"{box}/frp"] = np.ones(4)
    counts = F.fire_features(row, firms)[0]
    assert list(counts[:3]) == [2.0, 3.0, 2.0]  # 24 h, 72 h, FRP over 24 h for box a
