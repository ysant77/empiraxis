"""ERA5 versus IMERG hourly rain over one box: two related estimates, neither is truth.

ERA5 `tp` at stamp t is the amount (mm) in the hour ending at t. IMERG half-hour file with
start S covers [S, S+30 min). The hour ending at t uses the files starting at t-60 min and
t-30 min. A missing half hour makes the hour missing; no hour is set to zero.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from earthlab.m5.imerg import RainGrid, hour_total_mm


def imerg_hour_ending(grids: dict[datetime, RainGrid], end: datetime) -> float:
    """IMERG mm in the hour ending at `end` (UTC) from grids keyed by half-hour start time."""
    first, second = end - timedelta(minutes=60), end - timedelta(minutes=30)
    if first not in grids or second not in grids:
        return float("nan")
    return hour_total_mm(grids[first], grids[second])


def compare(era5_mm: np.ndarray, imerg_mm: np.ndarray) -> dict[str, Any]:
    """Pair statistics on hours where both exist. Wet hour: more than 0.1 mm."""
    ok = ~np.isnan(era5_mm) & ~np.isnan(imerg_mm)
    a, b = era5_mm[ok], imerg_mm[ok]
    out: dict[str, Any] = {"hours_paired": int(ok.sum()), "hours_total": len(era5_mm)}
    if ok.sum() < 8:
        return out
    out.update({
        "era5_mean_mm_h": float(a.mean()), "imerg_mean_mm_h": float(b.mean()),
        "era5_wet_share": float((a > 0.1).mean()), "imerg_wet_share": float((b > 0.1).mean()),
        "spearman": float(spearmanr(a, b).statistic) if np.ptp(a) and np.ptp(b) else None,
        "mean_abs_difference_mm": float(np.abs(a - b).mean()),
    })  # fmt: skip
    return out


def lag_profile(era5: dict[datetime, float], ends: list[datetime], imerg_mm: np.ndarray,
                shifts: range = range(-6, 7)) -> dict[int, float | None]:  # fmt: skip
    """Spearman between IMERG at `ends` and ERA5 at ends + shift hours. A peak away from 0 would
    point to a timing difference; one wet day is too little to say."""
    out: dict[int, float | None] = {}
    for sh in shifts:
        a = np.array([era5.get(e + timedelta(hours=sh), np.nan) for e in ends])
        ok = ~np.isnan(a) & ~np.isnan(imerg_mm)
        out[sh] = float(spearmanr(a[ok], imerg_mm[ok]).statistic) if ok.sum() > 8 else None
    return out
