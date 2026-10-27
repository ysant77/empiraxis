"""Deterministic descriptive statistics for regional PM2.5 inside one time window.

These are observations only. Nothing here infers a cause, a forecast or a health effect.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from statistics import fmean

from earthlab.contracts import ALL_REGIONS, Region, Strict, TimeWindow
from earthlab.data.nea_pm25 import Pm25Dataset

MEAN_DECIMALS = 1


class Statistic(StrEnum):
    MAX = "max"
    MEAN = "mean"


class RegionSummary(Strict):
    region: Region
    observed_hours: int
    missing_hours: int
    mean: float | None
    max: float | None
    max_at: datetime | None
    min: float | None


class DailyPeak(Strict):
    day: date
    max: float | None
    max_at: datetime | None
    observed_hours: int


class RankedRegion(Strict):
    region: Region
    value: float | None
    observed_hours: int


def _observed(
    dataset: Pm25Dataset, window: TimeWindow, region: Region
) -> list[tuple[datetime, float]]:
    pairs: list[tuple[datetime, float]] = []
    for row in dataset.in_window(window):
        value = row.values.get(region)
        if value is not None:
            pairs.append((row.time, value))
    return pairs


def _peak(pairs: list[tuple[datetime, float]]) -> tuple[float | None, datetime | None]:
    """Highest value; ties go to the earliest hour."""
    if not pairs:
        return None, None
    best_time, best_value = pairs[0]
    for moment, value in pairs[1:]:
        if value > best_value:
            best_time, best_value = moment, value
    return best_value, best_time


def summarize(dataset: Pm25Dataset, window: TimeWindow, region: Region) -> RegionSummary:
    pairs = _observed(dataset, window, region)
    peak, peak_at = _peak(pairs)
    values = [v for _, v in pairs]
    return RegionSummary(
        region=region,
        observed_hours=len(values),
        missing_hours=len(window.hours()) - len(values),
        mean=round(fmean(values), MEAN_DECIMALS) if values else None,
        max=peak,
        max_at=peak_at,
        min=min(values) if values else None,
    )


def daily_peaks(dataset: Pm25Dataset, window: TimeWindow, region: Region) -> list[DailyPeak]:
    by_day: dict[date, list[tuple[datetime, float]]] = {}
    for moment in window.hours():
        by_day.setdefault(moment.date(), [])
    for moment, value in _observed(dataset, window, region):
        by_day[moment.date()].append((moment, value))
    peaks: list[DailyPeak] = []
    for day, pairs in sorted(by_day.items()):
        peak, peak_at = _peak(pairs)
        peaks.append(DailyPeak(day=day, max=peak, max_at=peak_at, observed_hours=len(pairs)))
    return peaks


def hours_above(dataset: Pm25Dataset, window: TimeWindow, region: Region, threshold: float) -> int:
    """Count observed hours strictly above the threshold. Missing hours never count."""
    return sum(1 for _, value in _observed(dataset, window, region) if value > threshold)


def rank_regions(
    dataset: Pm25Dataset, window: TimeWindow, statistic: Statistic
) -> list[RankedRegion]:
    """Regions from highest to lowest; regions with no data go last."""
    ranked: list[RankedRegion] = []
    for region in ALL_REGIONS:
        summary = summarize(dataset, window, region)
        value = summary.max if statistic is Statistic.MAX else summary.mean
        ranked.append(
            RankedRegion(region=region, value=value, observed_hours=summary.observed_hours)
        )
    return sorted(ranked, key=lambda r: (r.value is None, -(r.value or 0.0)))
