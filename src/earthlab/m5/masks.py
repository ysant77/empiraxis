"""Fill-value handling, coverage statistics and QA bit decoding. Rejected cells stay missing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

# HLS v2 Fmask bits (LP DAAC HLS user guide): 0 cirrus, 1 cloud, 2 adjacent cloud or shadow,
# 3 cloud shadow, 4 snow or ice, 5 water, 6-7 aerosol level.
FMASK_CIRRUS, FMASK_CLOUD, FMASK_ADJACENT, FMASK_SHADOW, FMASK_SNOW, FMASK_WATER = (
    1, 2, 4, 8, 16, 32,
)  # fmt: skip
FMASK_BAD = FMASK_CLOUD | FMASK_ADJACENT | FMASK_SHADOW | FMASK_SNOW


@dataclass(frozen=True)
class Coverage:
    """Mean over valid cells and the share of cells that were valid."""

    mean: float
    valid_fraction: float
    n_valid: int
    n_total: int


def with_fill_as_nan(values: NDArray[np.number], fill: float) -> NDArray[np.float64]:
    """Replace the documented fill value by NaN. A fill value is not a measurement."""
    out = values.astype(np.float64, copy=True)
    out[values == fill] = np.nan
    return out


def coverage_mean(values: NDArray[np.float64], min_fraction: float) -> Coverage:
    """Mean of the valid cells, or NaN when too few cells are valid. Never zero-fills."""
    if not 0.0 < min_fraction <= 1.0:
        raise ValueError("min_fraction must be in (0, 1]")
    total = int(values.size)
    valid = values[~np.isnan(values)]
    fraction = len(valid) / total if total else 0.0
    mean = float(valid.mean()) if len(valid) and fraction >= min_fraction else float("nan")
    return Coverage(mean=mean, valid_fraction=fraction, n_valid=len(valid), n_total=total)


def hls_clear_land(fmask: NDArray[np.integer]) -> NDArray[np.bool_]:
    """True where HLS Fmask shows no cloud, adjacent cloud, shadow, snow or water."""
    f = fmask.astype(np.uint8)
    return np.asarray((f & (FMASK_BAD | FMASK_WATER)) == 0)


def hls_aerosol_level(fmask: NDArray[np.integer]) -> NDArray[np.uint8]:
    """Aerosol level from bits 6-7: 0 climatology, 1 low, 2 moderate, 3 high."""
    return np.asarray((fmask.astype(np.uint8) >> 6) & 3, dtype=np.uint8)


def normalised_difference(
    a: NDArray[np.float64], b: NDArray[np.float64], valid: NDArray[np.bool_]
) -> NDArray[np.float64]:
    """(a - b) / (a + b) where valid and the denominator is positive; NaN elsewhere."""
    out = np.full(a.shape, np.nan)
    denom = a + b
    ok = valid & ~np.isnan(a) & ~np.isnan(b) & (denom > 0)
    out[ok] = (a[ok] - b[ok]) / denom[ok]
    return out


def nbr(
    nir: NDArray[np.float64], swir2: NDArray[np.float64], valid: NDArray[np.bool_]
) -> NDArray[np.float64]:
    """Normalised burn ratio, (NIR - SWIR2) / (NIR + SWIR2). Landsat 8 HLS: B05 and B07."""
    return normalised_difference(nir, swir2, valid)


def ndvi(
    nir: NDArray[np.float64], red: NDArray[np.float64], valid: NDArray[np.bool_]
) -> NDArray[np.float64]:
    """Normalised difference vegetation index. Landsat 8 HLS: B05 and B04."""
    return normalised_difference(nir, red, valid)


def dnbr(pre: NDArray[np.float64], post: NDArray[np.float64]) -> NDArray[np.float64]:
    """Change in NBR, pre minus post. Valid only where both dates are valid."""
    return pre - post
