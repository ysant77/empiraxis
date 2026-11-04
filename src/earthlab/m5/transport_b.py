"""M5-B (protocol m5-protocol-b-1): fire exposure gated by wind direction, pooled over seasons.

Exposure per box and day is the FIRMS count times the share of hours with the 850 hPa wind
blowing from the box direction (within 45 degrees). Hindsight data is allowed. Nothing here
names a source or shows a cause: it ranks temporal association and compares it with controls.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from earthlab.haze.geometry import H1_SOURCE_BOXES
from earthlab.m5.assoc import Series
from earthlab.m5.assoc_data import DAYS, SGT, day_list

HALF_SECTOR = 45.0
MIN_HOURS = 18
FIRST_DAY = 3  # 4 September
MIN_SHIFT = 14
AUTOCORR_LIMIT = 0.2
MAX_LEAD = 14


def wind_from_deg(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Meteorological direction the wind blows from, in degrees clockwise from north."""
    return np.asarray(np.degrees(np.arctan2(-u, -v)) % 360.0)


def sector_share(extract: Path, box_id: str, year: int, offset_deg: float) -> Series:
    """Share of hours per Singapore day with the wind from within 45 degrees of the box bearing
    plus offset (0 for the real score, 180 for the negative control)."""
    box = next(b for b in H1_SOURCE_BOXES if b.box_id == box_id)
    target = (box.bearing_deg + offset_deg) % 360.0
    series = next(s for s in json.loads(extract.read_text())["series"] if s["box_id"] == box_id)
    index = {d: i for i, d in enumerate(day_list(year))}
    hits: list[list[float]] = [[] for _ in range(DAYS)]
    for h in series["hours"]:
        if h["u_ms"] is None or h["v_ms"] is None:
            continue
        when = datetime.fromisoformat(h["time"].replace("Z", "+00:00")).astimezone(UTC) + SGT
        if when.date() not in index:
            continue
        direction = float(wind_from_deg(np.array(h["u_ms"]), np.array(h["v_ms"])))
        gap = abs((direction - target + 180.0) % 360.0 - 180.0)
        hits[index[when.date()]].append(float(gap <= HALF_SECTOR))
    return np.array([np.mean(b) if len(b) >= MIN_HOURS else np.nan for b in hits])


def next_day_change(daily_pm: Series) -> Series:
    """PM2.5 on day d+1 minus day d, aligned to d. The last day is missing."""
    out = np.full(len(daily_pm), np.nan)
    out[:-1] = daily_pm[1:] - daily_pm[:-1]
    return out


def lead(exposure: Series, k: int) -> Series:
    """Exposure of day d+k aligned to day d; the last k days are missing."""
    out = np.full(len(exposure), np.nan)
    out[: len(exposure) - k] = exposure[k:]
    return out


def pooled_rho(xs: list[Series], ys: list[Series]) -> float:
    x, y = np.concatenate(xs), np.concatenate(ys)
    ok = ~np.isnan(x) & ~np.isnan(y)
    if ok.sum() < 8 or np.ptp(x[ok]) == 0 or np.ptp(y[ok]) == 0:
        return float("nan")
    return float(spearmanr(x[ok], y[ok]).statistic)


def pick_lead(exposures: list[Series]) -> dict[str, Any]:
    """Smallest k of 2 or more days where the pooled lag-k autocorrelation is under 0.2."""
    table: dict[str, float] = {}
    for k in range(1, MAX_LEAD + 1):
        a = np.concatenate([e[:-k] for e in exposures])
        b = np.concatenate([e[k:] for e in exposures])
        ok = ~np.isnan(a) & ~np.isnan(b)
        table[str(k)] = float(np.corrcoef(a[ok], b[ok])[0, 1]) if ok.sum() > 8 else float("nan")
    chosen = next((k for k in range(2, MAX_LEAD + 1) if table[str(k)] < AUTOCORR_LIMIT), None)
    return {"autocorrelation": table, "k": chosen}


def shift_p(xs: list[Series], ys: list[Series], draws: int, seed: int) -> float:
    """Two-sided p from independent circular shifts per season (each 14 days or more)."""
    rng = np.random.default_rng(seed)
    observed = abs(pooled_rho(xs, ys))
    null = []
    for _ in range(draws):
        rolled = [np.roll(x, int(rng.integers(MIN_SHIFT, len(x) - MIN_SHIFT + 1))) for x in xs]
        null.append(abs(pooled_rho(rolled, ys)))
    arr = np.array(null)
    return float((1 + np.sum(arr[~np.isnan(arr)] >= observed)) / (1 + np.sum(~np.isnan(arr))))


def boot_indices(sizes: list[int], block: int, resamples: int, seed: int) -> list[list[np.ndarray]]:
    """Moving-block indices per season, shared by every series so contrasts are paired."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(resamples):
        draw = []
        for n in sizes:
            starts = rng.integers(0, n - block + 1, size=-(-n // block))
            draw.append(np.concatenate([np.arange(s, s + block) for s in starts])[:n])
        out.append(draw)
    return out


def boot_rho(xs: list[Series], ys: list[Series], idx: list[list[np.ndarray]]) -> np.ndarray:
    return np.array(
        [pooled_rho([x[i] for x, i in zip(xs, d, strict=True)],
                    [y[i] for y, i in zip(ys, d, strict=True)]) for d in idx]
    )  # fmt: skip


def interval(draws: np.ndarray) -> tuple[float, float]:
    low, high = np.nanpercentile(draws, [2.5, 97.5])
    return float(low), float(high)


def label(rho: float, p_holm: float, contrasts: dict[str, tuple[float, float]]) -> str:
    """The only labels allowed by the protocol. Each contrast is an interval of (real - control)."""
    if np.isnan(rho):
        return "not_distinguishable"
    if rho < 0:
        return "unsupported_attribution"
    if not contrasts:
        return "not_distinguishable"
    if p_holm < 0.05 and all(low > 0 for low, _ in contrasts.values()):
        return "consistent_with_transport"
    return "not_distinguishable"


def day_window() -> slice:
    return slice(FIRST_DAY, DAYS - 1)  # d from 4 Sep to 30 Oct; d+1 stays inside the window
