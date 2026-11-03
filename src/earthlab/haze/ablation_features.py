"""Feature groups for the 2015 haze ablation, indexed so none reads a time after its limit.

Protocol: docs/haze-2015-ablation-protocol.md. PM2.5 lags are per region. ERA5 and FIRMS values
are one shared context per box, never joined to a region. Time limits: PM2.5 to T-2 h, ERA5 to
T-1 h UTC, FIRMS when the pass time plus 3 h is at or before T. ERA5 is a reanalysis made later
with hindsight, so its values were not available at T even though their times are before T.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from earthlab.forecast.dataset import Grid, index_of, label_at

BOXES = ("box-a", "box-b", "box-c")
LEVELS = ("10m", "850hPa")
LAGS, NEWEST, HORIZON = 24, 2, 6
FIRMS_DELAY = timedelta(hours=3)
SGT = timedelta(hours=8)
FIRST_ISSUE, LAST_ISSUE = datetime(2015, 9, 4, 0), datetime(2015, 10, 31, 17)


def issues() -> np.ndarray:
    return np.arange(index_of(FIRST_ISSUE), index_of(LAST_ISSUE) + 1, dtype=np.int64)


def utc_of(issue: int) -> datetime:
    """The issue time in UTC. NEA labels are Singapore local time."""
    return (label_at(int(issue)) - SGT).replace(tzinfo=UTC)


def pm25_lags(grid: Grid, rows: np.ndarray, region: int) -> np.ndarray:
    return np.stack([grid.values[rows - NEWEST - k, region] for k in range(LAGS)], axis=1)


def target(grid: Grid, rows: np.ndarray, region: int) -> np.ndarray:
    return np.asarray(grid.values[rows + HORIZON, region], dtype=float)


def load_met(folder: Path) -> tuple[datetime, dict[str, np.ndarray]]:
    """Hourly box means by name, such as box-a/10m/u. The first hour is returned too."""
    out: dict[str, np.ndarray] = {}
    start = None
    for level in LEVELS:
        name = "extract_10m.json" if level == "10m" else "extract_850hpa.json"
        for series in json.loads((folder / name).read_text())["series"]:
            hours = series["hours"]
            start = datetime.fromisoformat(hours[0]["time"].replace("Z", "+00:00"))
            for key in ("u_ms", "v_ms", "precip_mm"):
                values = [np.nan if h[key] is None else h[key] for h in hours]
                out[f"{series['box_id']}/{level}/{key}"] = np.array(values, dtype=float)
    if start is None:
        raise ValueError("no ERA5 series found")
    return start, out


def met_features(rows: np.ndarray, start: datetime, met: dict[str, np.ndarray]) -> np.ndarray:
    """u and v at T-1 h and their 6 h means; 10 m rain at T-1 h and its 6 h sum."""
    at = np.array([int((utc_of(i) - start).total_seconds() // 3600) - 1 for i in rows])
    if at.min() < 5:
        raise ValueError("an issue needs ERA5 hours before the series starts")
    cols = []
    for box in BOXES:
        for level in LEVELS:
            for part in ("u_ms", "v_ms"):
                series = met[f"{box}/{level}/{part}"]
                cols += [series[at], np.mean([series[at - k] for k in range(6)], axis=0)]
        rain = met[f"{box}/10m/precip_mm"]
        cols += [rain[at], np.sum([rain[at - k] for k in range(6)], axis=0)]
    return np.stack(cols, axis=1)


def load_firms(folder: Path) -> dict[str, np.ndarray]:
    """Per box: pass times in UTC seconds and FRP."""
    out = {}
    for box in BOXES:
        path = next((folder / box).glob("*.csv"))
        times, frp = [], []
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                hhmm = row["acq_time"].zfill(4)
                when = datetime.fromisoformat(f"{row['acq_date']}T{hhmm[:2]}:{hhmm[2:]}+00:00")
                times.append(when.timestamp())
                frp.append(float(row["frp"]))
        order = np.argsort(times)
        out[f"{box}/t"], out[f"{box}/frp"] = np.array(times)[order], np.array(frp)[order]
    return out


def fire_features(rows: np.ndarray, firms: dict[str, np.ndarray]) -> np.ndarray:
    """Per box: detection counts over 24 h and 72 h of pass times, and FRP over 24 h.

    Each window holds passes in (T-3h-W, T-3h]: W hours of passes that are visible at T.
    """
    cols = []
    for box in BOXES:
        t, frp = firms[f"{box}/t"], firms[f"{box}/frp"]
        visible = np.array([(utc_of(i) - FIRMS_DELAY).timestamp() for i in rows])
        for hours in (24, 72):
            low = visible - hours * 3600
            counts = np.searchsorted(t, visible, "right") - np.searchsorted(t, low, "right")
            cols.append(counts.astype(float))
        low = visible - 24 * 3600
        cum = np.concatenate([[0.0], np.cumsum(frp)])
        hi, lo = np.searchsorted(t, visible, "right"), np.searchsorted(t, low, "right")
        cols.append(cum[hi] - cum[lo])
    return np.stack(cols, axis=1)
