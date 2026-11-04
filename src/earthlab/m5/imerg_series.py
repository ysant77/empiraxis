"""IMERG Early corridor series and the issue-time rain features of rung I1 (Amendment 4).

A granule is reduced to one mean rain rate (mm/h) per H1 corridor. A half hour starting at S is
visible at issue time T when S + 30 min + latency is at or before T. Window sums multiply each
rate by 0.5 h. A window with any missing half hour is missing; nothing becomes zero.
"""

from __future__ import annotations

import csv
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from earthlab.haze.geometry import H1_SOURCE_BOXES, corridor
from earthlab.m5 import imerg

BOX_IDS = tuple(b.box_id for b in H1_SOURCE_BOXES)
FIELDS = ("start_utc", *BOX_IDS)
LATENCY_H = 4.0
WINDOWS_H = (6, 24)
HALF = timedelta(minutes=30)
Series = dict[datetime, dict[str, float]]


def granule_start(name: str) -> datetime:
    m = re.search(r"IMERG\.(\d{8})-S(\d{6})", name)
    if m is None:
        raise ValueError(f"not an IMERG granule name: {name}")
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def reduce_granule(path: Path) -> dict[str, float]:
    """Corridor mean rain rate (mm/h) per box; NaN when no cell is valid."""
    return {b.box_id: imerg.box_mean_rate(imerg.read_box(path, corridor(b)))
            for b in H1_SOURCE_BOXES}  # fmt: skip


def write_rows(path: Path, rows: Series) -> None:
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(FIELDS)
        for start in sorted(rows):
            cells = ["" if np.isnan(rows[start][b]) else f"{rows[start][b]:.6f}" for b in BOX_IDS]
            w.writerow([start.isoformat(), *cells])


def load_series(path: Path) -> Series:
    out: Series = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[datetime.fromisoformat(row["start_utc"])] = {
                b: float(row[b]) if row[b] != "" else float("nan") for b in BOX_IDS
            }
    return out


def window_sum(series: Series, box: str, issue: datetime, hours: int) -> float:
    """Rain (mm) over the `hours` before the newest visible half hour; NaN if any is missing."""
    last_end = issue - timedelta(hours=LATENCY_H)
    total = 0.0
    for k in range(2 * hours):
        start = last_end - HALF * (k + 1)
        value = series.get(start, {}).get(box, float("nan"))
        if np.isnan(value):
            return float("nan")
        total += value * 0.5
    return total


def features(issues: list[datetime], series: Series) -> NDArray[np.float64]:
    """(n, 6): per box, the 6 h and 24 h sums visible at each issue time (UTC)."""
    return np.array([[window_sum(series, b, t, h) for b in BOX_IDS for h in WINDOWS_H]
                     for t in issues], dtype=np.float64)  # fmt: skip
