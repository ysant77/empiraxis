"""Explicit checks of wind and rain meaning, kept apart from the H1 sector logic.

Four facts are easy to get wrong. A wind vector points to where the air goes, and a
meteorological bearing names where it comes from. A rain total over an interval is not a
rate. A series that grows through the day is an accumulation, not hourly rain. A lagged join
needs a regular hourly clock. Each check returns a typed result and never fixes data quietly.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.haze.sector import MetSeries
from earthlab.haze.wind import angular_difference, normalise_bearing, wind_from_uv

SIGN_CASES: tuple[tuple[str, float, float, float], ...] = (
    ("westerly (air moves east)", 5.0, 0.0, 270.0),
    ("easterly (air moves west)", -5.0, 0.0, 90.0),
    ("southerly (air moves north)", 0.0, 5.0, 180.0),
    ("northerly (air moves south)", 0.0, -5.0, 0.0),
    ("north-westerly (air moves south-east)", 3.0, -3.0, 315.0),
)
MAX_PLAUSIBLE_MM_H = 100.0
CUMULATIVE_RUN = 18
RISING_SHARE = 0.8
SIGN_TOLERANCE_DEG = 10.0


class SignResult(Strict):
    case: str
    expected_from_deg: float
    got_from_deg: float | None
    passed: bool


def speed_ms(u_ms: float, v_ms: float) -> float:
    """Wind speed from the vector components."""
    return math.hypot(u_ms, v_ms)


def towards_bearing(u_ms: float, v_ms: float) -> float:
    """Bearing the air moves TOWARDS, clockwise from north. The opposite of wind-from."""
    return normalise_bearing(math.degrees(math.atan2(u_ms, v_ms)))


def sign_tests() -> tuple[SignResult, ...]:
    """Cardinal and diagonal vectors against the wind-from bearing they must give."""
    out = []
    for case, u, v, expected in SIGN_CASES:
        got = wind_from_uv(u, v).from_deg
        ok = got is not None and angular_difference(got, expected) < 1e-6
        out.append(SignResult(case=case, expected_from_deg=expected, got_from_deg=got, passed=ok))
    return tuple(out)


def wind_sign_error(u_ms: float, v_ms: float, claimed_from_deg: float) -> bool:
    """True when a claimed wind-from bearing is really the direction the air moves towards."""
    reading = wind_from_uv(u_ms, v_ms)
    if reading.from_deg is None:
        return False
    wrong = angular_difference(claimed_from_deg, towards_bearing(u_ms, v_ms))
    right = angular_difference(claimed_from_deg, reading.from_deg)
    return wrong <= SIGN_TOLERANCE_DEG < right


def accumulate_mm(hourly_mm: list[float], hours: int) -> list[float]:
    """Rolling sum of hour-ending rain over `hours` hours."""
    if hours < 1:
        raise ValueError("the window must be at least one hour")
    return [sum(hourly_mm[i - hours + 1 : i + 1]) for i in range(hours - 1, len(hourly_mm))]


def rate_mm_h(total_mm: float, interval_hours: float) -> float:
    """Mean rate of a rain total over an interval of known length."""
    if interval_hours <= 0:
        raise ValueError("the interval must be positive")
    return total_mm / interval_hours


class PrecipCheck(Strict):
    hours: int
    missing: int
    negative: int
    max_mm_h: float | None
    longest_rising_run: int
    looks_cumulative: bool
    implausible_rate: bool
    issues: tuple[str, ...] = ()


def _longest_rise(values: list[float]) -> int:
    """Longest run that never falls and rises at 80 percent of its steps. A dry run is not one."""
    best = steps = rises = 0
    for before, after in itertools.pairwise(values):
        if after < before:
            steps = rises = 0
            continue
        steps, rises = steps + 1, rises + (after > before)
        if rises >= RISING_SHARE * steps:
            best = max(best, steps)
    return best


def check_precip(values_mm: Sequence[float | None], unit: Literal["mm", "m"] = "mm") -> PrecipCheck:
    """Tell hourly rain from a running total, and a metre value from a millimetre value."""
    seen = [v for v in values_mm if v is not None]
    scale = 1000.0 if unit == "m" else 1.0
    top = max(seen) * scale if seen else None
    rise = _longest_rise(seen)
    cumulative = rise >= CUMULATIVE_RUN
    implausible = top is not None and top > MAX_PLAUSIBLE_MM_H
    issues = []
    if cumulative:
        issues.append(f"{rise} hours rise in a row: this looks like a running total")
    if implausible:
        issues.append(f"peak {top:.1f} mm/h is above {MAX_PLAUSIBLE_MM_H:.0f}: check the unit")
    if any(v < 0 for v in seen):
        issues.append("negative rain")
    return PrecipCheck(
        hours=len(values_mm), missing=len(values_mm) - len(seen),
        negative=sum(v < 0 for v in seen), max_mm_h=top, longest_rising_run=rise,
        looks_cumulative=cumulative, implausible_rate=implausible, issues=tuple(issues),
    )  # fmt: skip


class ClockCheck(Strict):
    box_id: str
    level: str
    hours: int
    first: datetime
    last: datetime
    gaps: int
    repeats: int
    off_hour: int
    passed: bool = Field(description="a regular hourly UTC clock with no gap")


def check_clock(series: MetSeries) -> ClockCheck:
    """A lagged join needs one value per UTC hour. Report gaps, repeats and off-hour stamps."""
    times = [h.time for h in series.hours]
    step = timedelta(hours=1)
    gaps = sum(b - a > step for a, b in itertools.pairwise(times))
    repeats = sum(b == a for a, b in itertools.pairwise(times))
    off = sum(bool(t.minute or t.second) for t in times)
    return ClockCheck(
        box_id=series.box_id, level=series.level, hours=len(times), first=times[0],
        last=times[-1], gaps=gaps, repeats=repeats, off_hour=off,
        passed=not (gaps or repeats or off),
    )  # fmt: skip
