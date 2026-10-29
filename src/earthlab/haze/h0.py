"""H0: descriptive summary of the pinned NEA 1-hour PM2.5 file. Evidence class: observation.

Per region: coverage, mean, maximum and hours in each NEA band. Per day: the same in
Singapore local days. Event periods are runs of at least three consecutive hours in which
the highest observed regional value is above 55 ug/m3 (above the NEA "Normal" band).
Missing values are never filled and never counted as zero.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from pydantic import Field

from earthlab.contracts import ALL_REGIONS, PM25_UNIT, Region, Strict, TimeWindow
from earthlab.data.nea_pm25 import Pm25Dataset
from earthlab.data.quality import coverage_report
from earthlab.haze.contracts import EvidenceClass
from earthlab.haze.evidence import Provenance, SourceRef

METHOD_ID = "haze-h0-pm25-descriptive"
METHOD_VERSION = "1"
NORMAL_MAX = 55.0
BAND_FLOORS = {"elevated": 55.0, "high": 150.0, "very_high": 250.0}  # value > floor
MIN_EVENT_HOURS = 3
LIMITATIONS = (
    "NEA values are regional values for five reporting regions, not station points.",
    "NEA does not state whether a label marks the start or the end of its hour.",
    "1-hour PM2.5 is not the 24-hour PSI and not an AQI.",
    "A PM2.5 rise alone does not identify its source.",
)
ONE_HOUR = timedelta(hours=1)


class RegionSummary(Strict):
    region: Region
    expected_hours: int
    observed_hours: int
    missing_hours: int
    mean_ug_m3: float | None
    max_ug_m3: float | None
    max_at: datetime | None
    hours_above: dict[str, int]


class DailySummary(Strict):
    day: date
    region: Region
    observed_hours: int
    mean_ug_m3: float | None
    max_ug_m3: float | None


class EventPeriod(Strict):
    """A run of hour labels [start, end) in Singapore time with the network peak above 55."""

    start: datetime
    end: datetime
    hours: int = Field(ge=MIN_EVENT_HOURS)
    peak_ug_m3: float
    peak_region: Region
    peak_at: datetime
    regions_above: tuple[Region, ...]


class H0Report(Strict):
    window: TimeWindow
    unit: str
    regions: tuple[RegionSummary, ...]
    daily: tuple[DailySummary, ...]
    events: tuple[EventPeriod, ...]
    event_hours: int
    control_hours: int
    parse_issue_counts: dict[str, int]
    provenance: Provenance


def _values(dataset: Pm25Dataset, moment: datetime) -> dict[Region, float]:
    row = dataset.at(moment)
    if row is None:
        return {}
    return {region: value for region, value in row.values.items() if value is not None}


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _region_summary(
    dataset: Pm25Dataset, hours: list[datetime], region: Region, missing: int
) -> RegionSummary:
    series = [(h, v) for h in hours if (v := _values(dataset, h).get(region)) is not None]
    peak = max(series, key=lambda item: item[1], default=None)
    return RegionSummary(
        region=region,
        expected_hours=len(hours),
        observed_hours=len(series),
        missing_hours=missing,
        mean_ug_m3=_mean([v for _, v in series]),
        max_ug_m3=None if peak is None else peak[1],
        max_at=None if peak is None else peak[0],
        hours_above={
            band: sum(v > floor for _, v in series) for band, floor in BAND_FLOORS.items()
        },
    )


def _daily(dataset: Pm25Dataset, hours: list[datetime]) -> list[DailySummary]:
    by_day: dict[tuple[date, Region], list[float]] = {}
    for moment in hours:
        observed = _values(dataset, moment)
        for region in ALL_REGIONS:
            bucket = by_day.setdefault((moment.date(), region), [])
            if region in observed:
                bucket.append(observed[region])
    return [
        DailySummary(
            day=day,
            region=region,
            observed_hours=len(values),
            mean_ug_m3=_mean(values),
            max_ug_m3=max(values, default=None),
        )
        for (day, region), values in by_day.items()
    ]


def _close_event(run: list[tuple[datetime, dict[Region, float]]]) -> EventPeriod | None:
    if len(run) < MIN_EVENT_HOURS:
        return None
    peak_at, peak_values = max(run, key=lambda item: max(item[1].values()))
    peak_region = max(peak_values, key=lambda r: peak_values[r])
    above = {r for _, values in run for r, v in values.items() if v > NORMAL_MAX}
    return EventPeriod(
        start=run[0][0],
        end=run[-1][0] + ONE_HOUR,
        hours=len(run),
        peak_ug_m3=peak_values[peak_region],
        peak_region=peak_region,
        peak_at=peak_at,
        regions_above=tuple(r for r in ALL_REGIONS if r in above),
    )


def find_events(hourly: Iterable[tuple[datetime, dict[Region, float]]]) -> list[EventPeriod]:
    """Runs of consecutive hours whose highest observed value is above 55 ug/m3.

    An hour with no observed region, or a gap between labels, ends a run.
    """
    events: list[EventPeriod] = []
    run: list[tuple[datetime, dict[Region, float]]] = []
    for moment, values in hourly:
        contiguous = not run or run[-1][0] + ONE_HOUR == moment
        if values and max(values.values()) > NORMAL_MAX and contiguous:
            run.append((moment, values))
            continue
        if (event := _close_event(run)) is not None:
            events.append(event)
        run = [(moment, values)] if values and max(values.values()) > NORMAL_MAX else []
    if (event := _close_event(run)) is not None:
        events.append(event)
    return events


def is_control_hour(values: dict[Region, float]) -> bool:
    """All five regions observed and all at or below 55 ug/m3."""
    return len(values) == len(ALL_REGIONS) and max(values.values()) <= NORMAL_MAX


def describe(dataset: Pm25Dataset, window: TimeWindow, synthetic: bool = False) -> H0Report:
    hours = window.hours()
    hourly = [(h, _values(dataset, h)) for h in hours]
    coverage = coverage_report(dataset, window)
    events = find_events(hourly)
    snapshot = dataset.snapshot
    return H0Report(
        window=window,
        unit=PM25_UNIT,
        regions=tuple(
            _region_summary(dataset, hours, r, coverage.missing_for(r)) for r in ALL_REGIONS
        ),
        daily=tuple(_daily(dataset, hours)),
        events=tuple(events),
        event_hours=sum(e.hours for e in events),
        control_hours=sum(is_control_hour(values) for _, values in hourly),
        parse_issue_counts=dataset.issue_counts(),
        provenance=Provenance(
            evidence_class=EvidenceClass.OBSERVATION,
            method_id=METHOD_ID,
            method_version=METHOD_VERSION,
            sources=(
                SourceRef(
                    dataset_id=snapshot.dataset_id, file=snapshot.file, sha256=snapshot.sha256
                ),
            ),
            limitations=LIMITATIONS,
            parameters={"event_threshold_ug_m3": NORMAL_MAX, "min_event_hours": MIN_EVENT_HOURS},
            synthetic=synthetic,
        ),
    )
