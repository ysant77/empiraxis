"""Read hash-checked FIRMS detections with their UTC overpass times for the H1 check.

A detection is a thermal anomaly at overpass time. It is context for a source box, never
an emission amount, and zero detections is not zero fires.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.data.snapshot import SourceMismatchError
from earthlab.digest import file_digest
from earthlab.haze.evidence import SourceRef
from earthlab.haze.geometry import SourceBox


class FireDetection(Strict):
    time: datetime
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    confidence: int = Field(ge=0, le=100)


def _overpass(acq_date: str, acq_time: str) -> datetime:
    """FIRMS acq_date (YYYY-MM-DD) and acq_time (HHMM, leading zeros may be dropped), UTC."""
    hhmm = acq_time.strip().zfill(4)
    day = datetime.strptime(acq_date.strip(), "%Y-%m-%d").replace(tzinfo=UTC)
    return day + timedelta(hours=int(hhmm[:2]), minutes=int(hhmm[2:]))


def read_manifest(manifest_path: Path) -> tuple[list[FireDetection], list[SourceRef]]:
    """Every detection in the files of one FIRMS manifest, after each file's hash check."""
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    detections: list[FireDetection] = []
    refs: list[SourceRef] = []
    for entry in raw["files"]:
        path = manifest_path.parent / entry["file"]
        actual = file_digest(path)
        if actual != entry["sha256"]:
            raise SourceMismatchError(f"{entry['file']}: sha256 {actual[:12]}... does not match")
        refs.append(SourceRef(dataset_id=raw["asset_id"], file=entry["file"], sha256=actual))
        with path.open(encoding="utf-8", newline="") as stream:
            detections += [
                FireDetection(
                    time=_overpass(row["acq_date"], row["acq_time"]),
                    lat=float(row["latitude"]),
                    lon=float(row["longitude"]),
                    confidence=int(row["confidence"]),
                )
                for row in csv.DictReader(stream)
            ]
    return detections, refs


def count_in_window(
    detections: list[FireDetection],
    source: SourceBox,
    start: datetime,
    end: datetime,
    min_confidence: int,
) -> int:
    """Detections in the box, in [start, end), at or above the confidence floor."""
    box = source.box
    return sum(
        start <= d.time < end
        and d.confidence >= min_confidence
        and box.min_lat <= d.lat <= box.max_lat
        and box.min_lon <= d.lon <= box.max_lon
        for d in detections
    )
