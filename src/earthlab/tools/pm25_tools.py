"""Read-only PM2.5 tools the planner may call. Each result cites the pinned source."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from pydantic import Field, model_validator

from earthlab.contracts import Region, Strict, TimeWindow
from earthlab.data.nea_pm25 import Pm25Dataset
from earthlab.data.quality import coverage_report
from earthlab.science.episode import Statistic, daily_peaks, hours_above, rank_regions, summarize
from earthlab.tools.registry import ToolRegistry, ToolSpec

_TIME_HELP = "Singapore local time, ISO 8601 without offset, for example 2015-09-01T00:00"


class WindowArgs(Strict):
    start: datetime = Field(description=f"Window start (included). {_TIME_HELP}")
    end: datetime = Field(description=f"Window end (excluded). {_TIME_HELP}. Max 92 days.")

    @model_validator(mode="after")
    def _valid_window(self) -> Self:
        TimeWindow(start=self.start, end=self.end)
        return self

    @property
    def window(self) -> TimeWindow:
        return TimeWindow(start=self.start, end=self.end)


class SummarizeArgs(WindowArgs):
    regions: list[Region] | None = Field(default=None, description="Regions; omit for all five.")


class RegionArgs(WindowArgs):
    region: Region


class RankArgs(WindowArgs):
    statistic: Statistic = Field(description="Rank by the hourly maximum or the mean.")


class ThresholdArgs(RegionArgs):
    threshold: float = Field(ge=0, le=1000, description="Concentration in ug/m3; strictly above.")


class Pm25Toolset:
    """Binds the read-only tools to one hash-verified dataset."""

    def __init__(self, dataset: Pm25Dataset):
        self._dataset = dataset

    def _envelope(self, window: TimeWindow, payload: dict[str, Any]) -> dict[str, Any]:
        return {"window": window.label(), "source": self._dataset.snapshot.citation(), **payload}

    def inspect_coverage(self, args: WindowArgs) -> dict[str, Any]:
        report = coverage_report(self._dataset, args.window)
        return self._envelope(args.window, report.model_dump(mode="json", exclude={"window"}))

    def summarize_regions(self, args: SummarizeArgs) -> dict[str, Any]:
        regions = args.regions or list(Region)
        rows = [summarize(self._dataset, args.window, r).model_dump(mode="json") for r in regions]
        return self._envelope(args.window, {"summaries": rows})

    def daily_peaks(self, args: RegionArgs) -> dict[str, Any]:
        peaks = daily_peaks(self._dataset, args.window, args.region)
        rows = [p.model_dump(mode="json") for p in peaks]
        return self._envelope(args.window, {"region": args.region.value, "daily_peaks": rows})

    def rank_regions(self, args: RankArgs) -> dict[str, Any]:
        ranked = rank_regions(self._dataset, args.window, args.statistic)
        rows = [r.model_dump(mode="json") for r in ranked]
        return self._envelope(args.window, {"statistic": args.statistic.value, "ranking": rows})

    def count_hours_above(self, args: ThresholdArgs) -> dict[str, Any]:
        count = hours_above(self._dataset, args.window, args.region, args.threshold)
        observed = summarize(self._dataset, args.window, args.region).observed_hours
        payload = {
            "region": args.region.value,
            "threshold": args.threshold,
            "hours_above": count,
            "observed_hours": observed,
        }
        return self._envelope(args.window, payload)

    def register(self, registry: ToolRegistry) -> None:
        for spec in self.specs():
            registry.register(spec)

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                "inspect_coverage",
                "Count expected, observed and missing hours per region, and list gap runs and "
                "file-level data issues. Call this before drawing conclusions from a window.",
                WindowArgs,
                self.inspect_coverage,
            ),
            ToolSpec(
                "summarize_regions",
                "Observed mean (1 decimal), max with its hour, and min of hourly PM2.5 per region.",
                SummarizeArgs,
                self.summarize_regions,
            ),
            ToolSpec(
                "daily_peaks",
                "Highest hourly PM2.5 for each Singapore calendar day in the window, one region.",
                RegionArgs,
                self.daily_peaks,
            ),
            ToolSpec(
                "rank_regions",
                "Rank the five regions by hourly maximum or mean for the window.",
                RankArgs,
                self.rank_regions,
            ),
            ToolSpec(
                "count_hours_above",
                "Count observed hours with PM2.5 strictly above a threshold in one region.",
                ThresholdArgs,
                self.count_hours_above,
            ),
        ]
