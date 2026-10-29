"""Synthetic haze inputs for tests: an NEA-format PM2.5 folder and corridor wind series.

Every value here is made up. Nothing is read from, or derived from, real data or the
sealed held-out set.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from earthlab.contracts import SGT
from earthlab.haze.evidence import SourceRef
from earthlab.haze.geometry import H1_SOURCE_BOXES
from earthlab.haze.sector import MetHour, MetSeries
from earthlab.haze.wind import uv_from_wind

START_SGT = datetime(2015, 9, 1, tzinfo=SGT)
HOURS = 61 * 24
SYNTHETIC_REF = SourceRef(dataset_id="synthetic-era5", file="synthetic.grib", sha256="0" * 64)

Pm25Rule = Callable[[datetime], tuple[float | None, ...]]


def calm_air(moment: datetime) -> tuple[float | None, ...]:
    return (30.0, 32.0, 34.0, 31.0, 33.0)


def write_nea(folder: Path, rule: Pm25Rule = calm_air) -> Path:
    """An NEA-format CSV for Sep-Oct 2015 and a manifest with its real hash."""
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["1hr_pm25,north,south,east,west,central"]
    for hour in range(HOURS):
        moment = START_SGT + timedelta(hours=hour)
        cells = ["" if v is None else f"{v:g}" for v in rule(moment)]
        lines.append(
            f"{moment.day}/{moment.month}/{moment.year} {moment.hour}:00," + ",".join(cells)
        )
    data = ("\n".join(lines) + "\n").encode()
    (folder / "synthetic_pm25.csv").write_bytes(data)
    manifest = {
        "dataset_id": "synthetic-nea-pm25",
        "title": "Synthetic 1-hr PM2.5",
        "publisher": "test fixture",
        "source_url": "https://example.invalid/synthetic",
        "licence": "synthetic",
        "licence_url": "https://example.invalid/licence",
        "attribution": "synthetic",
        "file": "synthetic_pm25.csv",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "retrieved_at_utc": "2026-10-29T00:00:00Z",
        "timezone": "Asia/Singapore",
        "time_label_convention": "synthetic",
        "unit": "ug/m3",
        "measure": "synthetic",
        "spatial_support": "synthetic regions",
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def episode(start_sgt: datetime, hours: int, value: float) -> Pm25Rule:
    """Normal air, with every region at value during [start, start + hours)."""

    def rule(moment: datetime) -> tuple[float | None, ...]:
        if start_sgt <= moment < start_sgt + timedelta(hours=hours):
            return (value,) * 5
        return calm_air(moment)

    return rule


WindRule = Callable[[datetime, float], tuple[float, float, float]]


def steady(speed: float, rain: float = 0.0) -> WindRule:
    """Wind from each box's own bearing at a fixed speed: (speed, from_deg, rain_mm)."""
    return lambda moment, bearing: (speed, bearing, rain)


def met_series(rule: WindRule, level: Literal["10m", "850hPa"] = "10m") -> dict[str, MetSeries]:
    """Hourly corridor series for every source box over 2015-08-28 to 2015-11-01 UTC."""
    first = datetime(2015, 8, 28, tzinfo=UTC)
    series: dict[str, MetSeries] = {}
    for source in H1_SOURCE_BOXES:
        hours = []
        for hour in range(65 * 24):
            moment = first + timedelta(hours=hour)
            speed, from_deg, rain = rule(moment, source.bearing_deg)
            u, v = uv_from_wind(speed, from_deg)
            hours.append(MetHour(time=moment, u_ms=u, v_ms=v, precip_mm=rain))
        series[source.box_id] = MetSeries(
            box_id=source.box_id,
            level=level,
            hours=tuple(hours),
            sources=(SYNTHETIC_REF,),
        )
    return series
