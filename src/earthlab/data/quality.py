"""Coverage and data-quality report for one time window. Missing data is never zero."""

from __future__ import annotations

from datetime import datetime, timedelta

from earthlab.contracts import ALL_REGIONS, Region, Strict, TimeWindow
from earthlab.data.nea_pm25 import Pm25Dataset

MAX_LISTED_GAPS = 10


class Gap(Strict):
    start: datetime
    hours: int


class RegionCoverage(Strict):
    region: Region
    expected_hours: int
    observed_hours: int
    missing_hours: int
    gaps: tuple[Gap, ...]


class CoverageReport(Strict):
    window: TimeWindow
    regions: tuple[RegionCoverage, ...]
    file_issue_counts: dict[str, int]

    def missing_for(self, region: Region) -> int:
        return next(c.missing_hours for c in self.regions if c.region == region)


def _gaps(missing: list[datetime]) -> list[Gap]:
    """Group consecutive missing hours into runs."""
    runs: list[Gap] = []
    for moment in missing:
        if runs and runs[-1].start + timedelta(hours=runs[-1].hours) == moment:
            last = runs[-1]
            runs[-1] = Gap(start=last.start, hours=last.hours + 1)
        else:
            runs.append(Gap(start=moment, hours=1))
    return runs


def _region_coverage(dataset: Pm25Dataset, hours: list[datetime], region: Region) -> RegionCoverage:
    missing: list[datetime] = []
    for moment in hours:
        row = dataset.at(moment)
        if row is None or row.values.get(region) is None:
            missing.append(moment)
    return RegionCoverage(
        region=region,
        expected_hours=len(hours),
        observed_hours=len(hours) - len(missing),
        missing_hours=len(missing),
        gaps=tuple(_gaps(missing)[:MAX_LISTED_GAPS]),
    )


def coverage_report(dataset: Pm25Dataset, window: TimeWindow) -> CoverageReport:
    hours = window.hours()
    return CoverageReport(
        window=window,
        regions=tuple(_region_coverage(dataset, hours, region) for region in ALL_REGIONS),
        file_issue_counts=dataset.issue_counts(),
    )
