"""Daily series for Experiment A: PM2.5 outcome, FIRMS counts, ERA5 transport and rain.

All days are Singapore civil days. ERA5 hours are UTC and move to Singapore days by +8 h.
Series cover 1 September to 31 October (61 days); the protocol window starts on day index 3.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

from earthlab.forecast.dataset import Grid, index_of
from earthlab.haze.geometry import H1_SOURCE_BOXES
from earthlab.haze.wind import downwind_unit_vector
from earthlab.m5.assoc import Series

DAYS = 61
SGT = timedelta(hours=8)
MIN_VALID = 0.8


def day_list(year: int) -> list[date]:
    return [date(year, 9, 1) + timedelta(days=i) for i in range(DAYS)]


def daily_outcome(grid: Grid, year: int) -> Series:
    """Mean PM2.5 over the five regions and 24 hours; NaN if under 80% of 120 values exist."""
    out = np.full(DAYS, np.nan)
    for i, d in enumerate(day_list(year)):
        first = index_of(datetime(d.year, d.month, d.day, 0))
        block = grid.values[first : first + 24, :]
        valid = block[~np.isnan(block)]
        if len(valid) >= MIN_VALID * block.size:
            out[i] = float(valid.mean())
    return out


def fire_daily(times_utc: np.ndarray, year: int) -> Series:
    """Detection counts per Singapore day from pass times (epoch seconds, UTC)."""
    days = day_list(year)
    index = {d: i for i, d in enumerate(days)}
    out = np.zeros(DAYS)
    for t in times_utc:
        d = (datetime.fromtimestamp(float(t), UTC) + SGT).date()
        if d in index:
            out[index[d]] += 1
    return out


def met_daily(extract: Path, box_id: str, year: int, field: str) -> Series:
    """Daily mean (u_ms, v_ms) or daily sum (precip_mm) of one box series, by Singapore day."""
    series = next(s for s in json.loads(extract.read_text())["series"] if s["box_id"] == box_id)
    days = day_list(year)
    index = {d: i for i, d in enumerate(days)}
    buckets: list[list[float]] = [[] for _ in range(DAYS)]
    for h in series["hours"]:
        when = datetime.fromisoformat(h["time"].replace("Z", "+00:00")) + SGT
        value = h[field]
        if when.date() in index and value is not None:
            buckets[index[when.date()]].append(float(value))
    agg = np.sum if field == "precip_mm" else np.mean
    return np.array([agg(b) if len(b) >= 18 else np.nan for b in buckets])


def transport_daily(extract_850: Path, box_id: str, year: int) -> Series:
    """850 hPa wind component toward Singapore along the box-to-receptor line (m/s)."""
    box = next(b for b in H1_SOURCE_BOXES if b.box_id == box_id)
    east, north = downwind_unit_vector(box.bearing_deg)
    u = met_daily(extract_850, box_id, year, "u_ms")
    v = met_daily(extract_850, box_id, year, "v_ms")
    return np.asarray(u * east + v * north, dtype=float)
