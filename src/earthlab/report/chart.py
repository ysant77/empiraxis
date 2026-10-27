"""Hourly regional PM2.5 chart for the report. Gaps stay gaps; nothing is interpolated."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from earthlab.contracts import ALL_REGIONS, TimeWindow
from earthlab.data.nea_pm25 import Pm25Dataset


def hourly_chart(dataset: Pm25Dataset, window: TimeWindow, out: Path) -> Path:
    rows = dataset.in_window(window)
    times = mdates.date2num([row.time for row in rows])  # type: ignore[no-untyped-call]
    fig, ax = plt.subplots(figsize=(11, 4.2), dpi=120)
    for region in ALL_REGIONS:
        values = [row.values.get(region) for row in rows]
        series = [float("nan") if v is None else v for v in values]
        ax.plot(times, series, linewidth=0.9, label=region.value)
    ax.xaxis_date(tz=window.start.tzinfo)
    ax.set_ylabel("PM2.5, 1-hour regional value (ug/m3)")
    ax.set_title(f"NEA regional 1-hr PM2.5, {window.label()}", fontsize=10)
    ax.legend(ncol=5, fontsize=8, loc="upper left")
    ax.grid(alpha=0.3)
    fig.text(
        0.01,
        0.01,
        f"Source: NEA via data.gov.sg (Singapore Open Data Licence). sha256 "
        f"{dataset.snapshot.sha256[:16]}... Regions are areas, not stations.",
        fontsize=7,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return out
