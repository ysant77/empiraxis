"""ERA5 versus IMERG hourly alignment and statistics."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from earthlab.m5.imerg import RainGrid
from earthlab.m5.rain_compare import compare, imerg_hour_ending, lag_profile


def grid(rate: float) -> RainGrid:
    return RainGrid(np.full((2, 2), rate), np.full((2, 2), 0.5), np.zeros(2), np.zeros(2))


def test_hour_ending_uses_the_two_preceding_half_hours() -> None:
    t = datetime(2015, 10, 19, 1, tzinfo=UTC)
    g = {t - timedelta(minutes=60): grid(4.0), t - timedelta(minutes=30): grid(2.0)}
    assert imerg_hour_ending(g, t) == pytest.approx(3.0)
    assert math.isnan(imerg_hour_ending(g, t + timedelta(minutes=30)))
    g[t - timedelta(minutes=30)] = grid(float("nan"))
    assert math.isnan(imerg_hour_ending(g, t))


def test_compare_pairs_only_present_hours() -> None:
    era = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, np.nan])
    imr = era * 2
    imr[1] = np.nan
    out = compare(era, imr)
    assert out["hours_paired"] == 8 and out["spearman"] == pytest.approx(1.0)
    assert compare(era[:3], imr[:3]) == {"hours_paired": 2, "hours_total": 3}


def test_lag_profile_peaks_at_the_true_shift() -> None:
    t0 = datetime(2015, 10, 30, tzinfo=UTC)
    rng = np.random.default_rng(3)
    vals = rng.gamma(0.5, 1.0, 60)
    era = {t0 + timedelta(hours=i): float(v) for i, v in enumerate(vals)}
    ends = [t0 + timedelta(hours=i) for i in range(10, 40)]
    imerg_mm = np.array([era[e + timedelta(hours=2)] for e in ends])
    prof = lag_profile(era, ends, imerg_mm)
    assert prof[2] == pytest.approx(1.0) and max(prof, key=lambda k: prof[k] or -1) == 2
