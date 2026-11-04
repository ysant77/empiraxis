"""SMAP reader on a small synthetic HDF5 file: fill, quality bit and no zero-filling."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from earthlab.cases.models import BoundingBox
from earthlab.m5.smap import granule_stats

BOX = BoundingBox(min_lon=113.8, min_lat=-3.2, max_lon=114.8, max_lat=-2.0)


def write_granule(path: Path) -> None:
    lat = np.array([[-2.5, -2.5, -2.5, -9999.0], [10.0, 10.0, -2.5, -2.5]], dtype=np.float32)
    lon = np.array([[114.0, 114.2, 114.4, -9999.0], [114.0, 114.2, 120.0, 114.1]], dtype=np.float32)
    sm = np.array([[0.30, -9999.0, 0.25, -9999.0], [0.2, 0.2, 0.2, 0.40]], dtype=np.float32)
    flag = np.array([[0, 65534, 9, 65534], [0, 0, 0, 0]], dtype=np.uint16)
    vwc = np.array([[3.0, -9999.0, 12.0, -9999.0], [1, 1, 1, 6.0]], dtype=np.float32)
    with h5py.File(path, "w") as f:
        for name, sfx in (("AM", ""), ("PM", "_pm")):
            g = f.create_group(f"Soil_Moisture_Retrieval_Data_{name}")
            arrays = {"latitude": lat, "longitude": lon, "soil_moisture": sm,
                      "retrieval_qual_flag": flag, "vegetation_water_content": vwc}  # fmt: skip
            for key, arr in arrays.items():
                g.create_dataset(f"{key}{sfx}", data=arr)


def test_box_counts_retrieved_and_recommended_cells(tmp_path: Path) -> None:
    path = tmp_path / "g.h5"
    write_granule(path)
    am, pm = granule_stats(path, BOX)
    assert (am.pass_name, pm.pass_name) == ("AM", "PM")
    # cells in the box: (0,0) (0,1) (0,2) and (1,3); (0,1) has no retrieval
    assert am.cells_in_box == 4 and am.retrieved == 3
    assert am.recommended == 2  # (0,0) flag 0 and (1,3) flag 0; (0,2) has flag 9, bit 0 set
    assert am.flag_values == {0: 2, 9: 1}
    assert am.vegetation_water_content_mean == pytest.approx((3.0 + 12.0 + 6.0) / 3)


def test_screened_values_are_nan_not_zero(tmp_path: Path) -> None:
    path = tmp_path / "g.h5"
    write_granule(path)
    am, _ = granule_stats(path, BOX)
    values = am.soil_moisture_screened
    assert len(values) == 4
    assert np.isnan(values).sum() == 2 and not (values == 0).any()
    assert sorted(values[~np.isnan(values)].tolist()) == pytest.approx([0.30, 0.40])
