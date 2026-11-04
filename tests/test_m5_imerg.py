"""IMERG reader on a synthetic file in the documented layout (not a real granule)."""

from __future__ import annotations

import math
from pathlib import Path

import h5py
import numpy as np
import pytest

from earthlab.cases.models import BoundingBox
from earthlab.m5 import imerg

BOX = BoundingBox(min_lon=103.6, min_lat=1.15, max_lon=104.1, max_lat=1.48)


def write(path: Path, value: float, fill_cell: bool = False) -> None:
    rain = np.full((1, 3600, 1800), value, dtype=np.float32)
    qual = np.full((1, 3600, 1800), 0.8, dtype=np.float32)
    if fill_cell:
        rain[0, :, :] = -9999.9
    with h5py.File(path, "w") as f:
        f.create_dataset("Grid/precipitation", data=rain)
        f.create_dataset("Grid/precipitationQualityIndex", data=qual)


def test_box_cells_and_units(tmp_path: Path) -> None:
    write(tmp_path / "a.h5", 2.0)
    grid = imerg.read_box(tmp_path / "a.h5", BOX)
    assert grid.rate_mm_h.shape == (len(grid.lats), len(grid.lons)) == (4, 5)
    assert grid.lons[0] == pytest.approx(103.65) and grid.lats[0] == pytest.approx(1.15, abs=0.06)
    assert imerg.box_mean_rate(grid) == pytest.approx(2.0)
    assert np.allclose(grid.quality, 0.8)


def test_fill_is_nan_and_missing_half_hour_makes_the_hour_missing(tmp_path: Path) -> None:
    write(tmp_path / "a.h5", 4.0)
    write(tmp_path / "b.h5", 0.0, fill_cell=True)
    a, b = imerg.read_box(tmp_path / "a.h5", BOX), imerg.read_box(tmp_path / "b.h5", BOX)
    assert np.isnan(b.rate_mm_h).all() and math.isnan(imerg.box_mean_rate(b))
    assert math.isnan(imerg.hour_total_mm(a, b))
    assert imerg.hour_total_mm(a, a) == pytest.approx(4.0)  # 4 mm/h for one hour
