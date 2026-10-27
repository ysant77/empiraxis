"""Count pinned FIRMS active-fire detections in a box and a UTC month, after a hash check.

A detection is a thermal anomaly at overpass time. The count is context for a burned-area
report; it never becomes burned area.
"""

from __future__ import annotations

import csv
from pathlib import Path

from earthlab.cases.models import BoundingBox
from earthlab.data.mcd64a1 import read_manifest
from earthlab.data.snapshot import SourceMismatchError
from earthlab.digest import file_digest


def detections_in_month(data_dir: Path, manifest_name: str, box: BoundingBox, month: str) -> int:
    """Detections whose UTC acquisition date falls in month (YYYY-MM) and inside box."""
    count = 0
    for entry in read_manifest(data_dir / manifest_name)["files"]:
        path = data_dir / entry["file"]
        actual = file_digest(path)
        if actual != entry["sha256"]:
            raise SourceMismatchError(f"{entry['file']}: sha256 {actual[:12]}... does not match")
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if not row["acq_date"].startswith(month):
                    continue
                lat, lon = float(row["latitude"]), float(row["longitude"])
                count += box.min_lat <= lat <= box.max_lat and box.min_lon <= lon <= box.max_lon
    return count
