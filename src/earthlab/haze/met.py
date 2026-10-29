"""Build corridor-mean hourly wind and rain series from hash-checked ERA5 grid fields.

A decoder turns one pinned ERA5 file into grid fields; this module averages each field
over a corridor box and joins u, v and precipitation by valid hour. ERA5 precipitation
is metres per hour; the series stores millimetres. The GRIB decoder is an adapter behind
the GridDecoder protocol; tests use a fake that yields synthetic fields.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

import numpy as np
import numpy.typing as npt

from earthlab.cases.models import BoundingBox
from earthlab.data.snapshot import SourceMismatchError
from earthlab.digest import file_digest
from earthlab.haze.evidence import SourceRef
from earthlab.haze.sector import MetHour, MetSeries
from earthlab.haze.timebase import to_utc

Level = Literal["10m", "850hPa"]
FIELD_ROLES: dict[Level, dict[str, str]] = {
    "10m": {"10u": "u", "10v": "v", "tp": "precip"},
    "850hPa": {"u": "u", "v": "v"},
}
M_TO_MM = 1000.0


@dataclass(frozen=True)
class GridField:
    """One decoded field at one valid time. lats and lons are 1-D cell-centre axes."""

    short_name: str
    level_hpa: int | None
    valid_time: datetime
    lats: npt.NDArray[np.float64]
    lons: npt.NDArray[np.float64]
    values: npt.NDArray[np.float64]


class GridDecoder(Protocol):
    def fields(self, path: Path) -> Iterator[GridField]: ...


class DecoderMissing(RuntimeError):
    """No GRIB decoder is installed; the ERA5 extract cannot be built yet."""


def verified_files(manifest_path: Path) -> list[tuple[Path, SourceRef]]:
    """Each file of an ERA5 manifest with its reference, after the hash check."""
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    checked: list[tuple[Path, SourceRef]] = []
    for entry in raw["files"]:
        path = manifest_path.parent / entry["file"]
        actual = file_digest(path)
        if actual != entry["sha256"]:
            raise SourceMismatchError(f"{entry['file']}: sha256 {actual[:12]}... does not match")
        checked.append(
            (path, SourceRef(dataset_id=raw["asset_id"], file=entry["file"], sha256=actual))
        )
    return checked


def box_mean(field: GridField, box: BoundingBox) -> float | None:
    """Mean of finite cells whose centre lies in the box; None when no cell qualifies."""
    rows = (field.lats >= box.min_lat) & (field.lats <= box.max_lat)
    cols = (field.lons >= box.min_lon) & (field.lons <= box.max_lon)
    cells = field.values[np.ix_(rows, cols)]
    finite = cells[np.isfinite(cells)]
    return float(finite.mean()) if finite.size else None


def _role(field: GridField, level: Level) -> str | None:
    if level == "850hPa" and field.level_hpa != 850:
        return None
    return FIELD_ROLES[level].get(field.short_name)


def corridor_series(
    fields: Iterable[GridField],
    corridor: BoundingBox,
    box_id: str,
    level: Level,
    sources: tuple[SourceRef, ...],
) -> MetSeries:
    """Join u, v and precipitation corridor means by valid UTC hour, in time order."""
    by_hour: dict[datetime, dict[str, float | None]] = {}
    for field in fields:
        role = _role(field, level)
        if role is None:
            continue
        mean = box_mean(field, corridor)
        if role == "precip" and mean is not None:
            mean *= M_TO_MM
        by_hour.setdefault(to_utc(field.valid_time), {})[role] = mean
    hours = tuple(
        MetHour(
            time=moment, u_ms=parts.get("u"), v_ms=parts.get("v"), precip_mm=parts.get("precip")
        )
        for moment, parts in sorted(by_hour.items())
    )
    return MetSeries(box_id=box_id, level=level, hours=hours, sources=sources)
