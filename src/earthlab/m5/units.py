"""Unit conversions for rainfall. A missing input gives a missing output, never zero.

ERA5 total precipitation is metres of water accumulated over the hour ending at the stamp.
IMERG precipitation is a rate in mm per hour, valid for a half hour. The two are different
quantities: a rate must be multiplied by its duration before it is summed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

M_TO_MM = 1000.0
IMERG_STEP_HOURS = 0.5


def era5_tp_m_to_mm(metres: float) -> float:
    """ERA5 `tp` (m per hour) to mm in that hour. Negative rounding noise is refused."""
    if math.isnan(metres):
        return math.nan
    if metres < -1e-9:
        raise ValueError(f"precipitation cannot be negative, got {metres!r}")
    return max(metres, 0.0) * M_TO_MM


def rate_to_accumulation_mm(rate_mm_h: float, hours: float) -> float:
    """Accumulation (mm) of a constant rate over a duration in hours."""
    if hours <= 0:
        raise ValueError("duration must be positive")
    if math.isnan(rate_mm_h):
        return math.nan
    if rate_mm_h < 0:
        raise ValueError(f"a rain rate cannot be negative, got {rate_mm_h!r}")
    return rate_mm_h * hours


def hourly_from_half_hourly(rates_mm_h: Sequence[float]) -> float:
    """One hour of IMERG (two half-hour rates) in mm. Any missing half hour makes the hour
    missing; the other half is not doubled and nothing is set to zero."""
    if len(rates_mm_h) != 2:
        raise ValueError("an hour holds exactly two half-hour rates")
    parts = [rate_to_accumulation_mm(r, IMERG_STEP_HOURS) for r in rates_mm_h]
    return math.nan if any(math.isnan(p) for p in parts) else sum(parts)
