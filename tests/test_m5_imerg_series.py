"""IMERG Early corridor series: granule names, CSV round trip and issue-time window sums."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import h5py
import numpy as np
import pytest

from earthlab.m5 import imerg
from earthlab.m5 import imerg_series as S

T0 = datetime(2015, 9, 1, tzinfo=UTC)
NAME = "3B-HHR-E.MS.MRG.3IMERG.20150901-S013000-E015959.0090.V07B.HDF5"


def test_granule_start_and_bad_name() -> None:
    assert S.granule_start(NAME) == datetime(2015, 9, 1, 1, 30, tzinfo=UTC)
    with pytest.raises(ValueError):
        S.granule_start("nope.h5")


def series(rate: float, n: int = 120) -> S.Series:
    return {T0 + S.HALF * i: dict.fromkeys(S.BOX_IDS, rate) for i in range(n)}


def test_window_sum_uses_only_half_hours_visible_at_issue() -> None:
    issue = T0 + timedelta(hours=30)
    s = series(2.0)
    assert S.window_sum(s, "box-a", issue, 6) == pytest.approx(
        12.0
    )  # 12 half hours x 2 mm/h x 0.5 h
    # a half hour that ends after issue - 4 h must not matter
    s[issue - timedelta(hours=4)] = dict.fromkeys(S.BOX_IDS, 99.0)
    assert S.window_sum(s, "box-a", issue, 6) == pytest.approx(12.0)
    s[issue - timedelta(hours=4, minutes=30)] = dict.fromkeys(S.BOX_IDS, 4.0)  # newest visible
    assert S.window_sum(s, "box-a", issue, 6) == pytest.approx(13.0)


def test_missing_half_hour_makes_the_window_missing_not_zero() -> None:
    issue = T0 + timedelta(hours=30)
    s = series(1.0)
    s[issue - timedelta(hours=8)] = dict.fromkeys(S.BOX_IDS, float("nan"))
    assert math.isnan(S.window_sum(s, "box-a", issue, 6))
    assert not math.isnan(S.window_sum(s, "box-a", issue, 2))
    assert math.isnan(S.window_sum({}, "box-a", issue, 6))
    out = S.features([issue], s)
    assert out.shape == (1, 6) and np.isnan(out[0, 0]) and np.isnan(out[0, 1])


def test_csv_round_trip_keeps_nan(tmp_path: Path) -> None:
    rows = {T0: {"box-a": 1.5, "box-b": float("nan"), "box-c": 0.0}}
    path = tmp_path / "s.csv"
    S.write_rows(path, rows)
    got = S.load_series(path)[T0]
    assert got["box-a"] == pytest.approx(1.5) and math.isnan(got["box-b"]) and got["box-c"] == 0.0


def test_reduce_granule_and_pin(tmp_path: Path) -> None:
    path = tmp_path / NAME
    with h5py.File(path, "w") as f:
        f.create_dataset("Grid/precipitation", data=np.full((1, 3600, 1800), 3.0, np.float32))
        f.create_dataset(
            "Grid/precipitationQualityIndex", data=np.ones((1, 3600, 1800), np.float32)
        )
    assert S.reduce_granule(path) == {b: pytest.approx(3.0) for b in S.BOX_IDS}
    assert imerg.pin("early").product == "GPM_3IMERGHHE" and imerg.pin("early").run == "early"
