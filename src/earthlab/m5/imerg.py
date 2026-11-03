"""GPM IMERG V07 half-hourly reader (HDF5 `Grid/precipitation`), written to the documented layout.

STATUS: not validated on a real file. GES DISC access was refused (HTTP 403) for the project's
Earthdata token, so no IMERG granule was read. The layout below comes from the product
documentation: group `Grid`, variable `precipitation` in mm/h with shape (time=1, lon, lat),
fill -9999.9, and `precipitationQualityIndex` in [0, 1]. A real-file test is still needed.

IMERG Early, Late and Final are different product runs. Only Early has a latency (about 4 h)
that could serve a 6 h forecast; Final is hindsight data for this horizon.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
from numpy.typing import NDArray

from earthlab.cases.models import BoundingBox
from earthlab.m5.units import hourly_from_half_hourly

FILL = -9999.9
STEP_DEG = 0.1
LON0, LAT0 = -179.95, -89.95  # centre of the first cell


@dataclass(frozen=True)
class RainGrid:
    rate_mm_h: NDArray[np.float64]  # (lat, lon) in the box; NaN where fill
    quality: NDArray[np.float64]
    lats: NDArray[np.float64]
    lons: NDArray[np.float64]


def _slice(start: float, lo: float, hi: float, n: int) -> slice:
    first = int(np.ceil((lo - start) / STEP_DEG - 1e-9))
    last = int(np.floor((hi - start) / STEP_DEG + 1e-9))
    return slice(max(first, 0), min(last, n - 1) + 1)


def read_box(path: Path, box: BoundingBox) -> RainGrid:
    """Rain rate and quality index for cells whose centre is in the box. Fill becomes NaN."""
    with h5py.File(path, "r") as f:
        rain, qual = f["Grid/precipitation"], f["Grid/precipitationQualityIndex"]
        n_lon, n_lat = rain.shape[1], rain.shape[2]
        cols, rows = (
            _slice(LON0, box.min_lon, box.max_lon, n_lon),
            _slice(LAT0, box.min_lat, box.max_lat, n_lat),
        )
        rate = np.asarray(rain[0, cols, rows], dtype=np.float64).T
        quality = np.asarray(qual[0, cols, rows], dtype=np.float64).T
    rate[rate <= FILL + 1e-3] = np.nan
    quality[quality <= FILL + 1e-3] = np.nan
    lons = LON0 + STEP_DEG * np.arange(cols.start, cols.stop)
    lats = LAT0 + STEP_DEG * np.arange(rows.start, rows.stop)
    return RainGrid(rate, quality, lats, lons)


def box_mean_rate(grid: RainGrid) -> float:
    """Mean of the valid cells (mm/h); NaN when no cell is valid. No zero fill."""
    valid = grid.rate_mm_h[~np.isnan(grid.rate_mm_h)]
    return float(valid.mean()) if valid.size else float("nan")


def hour_total_mm(first: RainGrid, second: RainGrid) -> float:
    """Box-mean rain for one hour from two consecutive half-hour grids (mm)."""
    return hourly_from_half_hourly([box_mean_rate(first), box_mean_rate(second)])
