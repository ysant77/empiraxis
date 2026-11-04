"""Scientific data layers for a viewer: what exists, its state, its sources and its limits.

A layer is listed even when it cannot be shown. Its `state` says why: `available`, `gated_out`
(failed a protocol gate), `blocked` (needs an owner step), `not_assessed`. A viewer must show
the state and the reason. It must not draw measurement pixels, wind vectors, plumes or
interpolation that the source files do not hold. Readers here return only values that a source
file holds, with their UTC times.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.m5 import strict_json as sj

State = Literal["available", "gated_out", "blocked", "not_assessed"]
Kind = Literal["points", "vector_series", "grid_series", "raster", "series"]


class LayerSpec(Strict):
    layer_id: str
    title: str
    kind: Kind
    state: State
    product: str
    version: str
    unit: str
    first_utc: datetime | None = None
    last_utc: datetime | None = None
    attribution: str
    hindsight: bool
    source_sha256: tuple[str, ...] = Field(default=())
    limits: tuple[str, ...] = ()
    reason: str | None = None

    def covers(self, day: date) -> bool:
        """True when the layer is available and the UTC day lies in its time range."""
        if self.state != "available" or self.first_utc is None or self.last_utc is None:
            return False
        return self.first_utc.date() <= day <= self.last_utc.date()


class FirePoint(Strict):
    time_utc: datetime
    lat: float
    lon: float
    frp_mw: float
    confidence: int
    satellite: str


def read_fire_points(csv_path: Path, day: date) -> list[FirePoint]:
    """The detections whose UTC pass date is `day`, exactly as the FIRMS file lists them."""
    points: list[FirePoint] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["acq_date"] != day.isoformat():
                continue
            hhmm = row["acq_time"].zfill(4)
            when = datetime.fromisoformat(f"{row['acq_date']}T{hhmm[:2]}:{hhmm[2:]}+00:00")
            points.append(FirePoint(
                time_utc=when, lat=float(row["latitude"]), lon=float(row["longitude"]),
                frp_mw=float(row["frp"]), confidence=int(float(row["confidence"])),
                satellite=row["satellite"]))  # fmt: skip
    return points


def read_wind_vector(extract: Path, box_id: str, when: datetime) -> tuple[float, float] | None:
    """(u, v) in m/s of a corridor-mean ERA5 series at a UTC hour; None when missing."""
    if when.tzinfo is None or when.utcoffset() != UTC.utcoffset(None):
        raise ValueError("time must be UTC")
    series = next(s for s in json.loads(extract.read_text())["series"] if s["box_id"] == box_id)
    stamp = when.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    for hour in series["hours"]:
        if hour["time"] == stamp:
            if hour["u_ms"] is None or hour["v_ms"] is None:
                return None
            return float(hour["u_ms"]), float(hour["v_ms"])
    return None


def catalogue_json(layers: list[LayerSpec]) -> str:
    return sj.dumps([json.loads(layer.model_dump_json()) for layer in layers], indent=2,
                      sort_keys=True) + "\n"  # fmt: skip
