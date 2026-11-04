"""Fetch ERA5 (10 m, 850 hPa) and FIRMS MODIS_SP boxes A, B, C for one Sep-Oct season.

Usage: FIRMS_API_KEY=... uv run python scripts/m5_acquire_season.py \
    DATA_ROOT YEAR [firms-only|era5-only]
Credentials come from ~/.cdsapirc (cdsapi) and the FIRMS_API_KEY variable. Caps: 60 MB per
ERA5 single-level month, 30 MB per pressure-level month, 15 MB per FIRMS box. Receipts are
written under DATA_ROOT/receipts. The layout matches runs/haze-2015 so the haze extract
commands read it unchanged.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from earthlab.acquire import era5, firms
from earthlab.cases.models import BoundingBox
from earthlab.digest import file_digest
from earthlab.m5.acquire import AUTHORITY

BOXES = {
    "box-a": BoundingBox(min_lon=100.0, min_lat=-1.5, max_lon=103.5, max_lat=2.0),
    "box-b": BoundingBox(min_lon=102.5, min_lat=-4.5, max_lon=106.5, max_lat=-1.0),
    "box-c": BoundingBox(min_lon=108.5, min_lat=-3.5, max_lon=115.0, max_lat=1.0),
}
ERA5_CAP = {era5.SINGLE_LEVELS: 60_000_000, era5.PRESSURE_LEVELS: 30_000_000}
FIRMS_CAP = 15_000_000


def fetch_era5(root: Path, year: int, receipts: list[dict[str, object]]) -> None:
    client = era5.client_from_config()
    start, end = datetime(year, 9, 1, tzinfo=UTC), datetime(year, 11, 1, tzinfo=UTC)
    for dataset in (era5.SINGLE_LEVELS, era5.PRESSURE_LEVELS):
        reqs = era5.monthly_requests(era5.H1_VARIABLES[dataset], era5.H1_LEVELS[dataset],
                                     era5.H1_BOX, start, end)  # fmt: skip
        for month, request in reqs:
            path = root / "era5" / era5.month_file(dataset, month)
            if path.exists():
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            sha, size = era5.fetch_month(client, dataset, request, path, ERA5_CAP[dataset])
            receipts.append({"file": path.name, "sha256": sha, "bytes": size, "dataset": dataset,
                             "retrieved_at_utc": datetime.now(UTC).isoformat()})  # fmt: skip
            print(path.name, size, flush=True)


def fetch_firms(root: Path, year: int, receipts: list[dict[str, object]]) -> None:
    key = os.environ["FIRMS_API_KEY"]
    first, last = date(year, 8, 25), date(year, 11, 1)
    with httpx.Client() as client:
        for name, box in BOXES.items():
            path = root / "firms" / name / "firms_modis_sp_season.csv"
            if path.exists():
                continue
            parts = firms.fetch_parts(key, "MODIS_SP", box, first, last, client)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = b"".join(firms.joined_csv(parts))
            if len(data) > FIRMS_CAP:
                raise RuntimeError(f"{name}: {len(data)} bytes exceed the cap")
            path.write_bytes(data)
            receipts.append({"file": f"{name}/{path.name}", "sha256": file_digest(path),
                             "bytes": len(data), "dataset": "FIRMS/MODIS_SP",
                             "retrieved_at_utc": datetime.now(UTC).isoformat()})  # fmt: skip
            print(name, len(data), flush=True)


def _suffix(flags: list[str]) -> str:
    return "_firms" if "firms-only" in flags else "_era5" if "era5-only" in flags else ""


def main() -> int:
    root = Path(sys.argv[1]).expanduser() / "season" / sys.argv[2]
    year = int(sys.argv[2])
    receipts: list[dict[str, object]] = []
    if "era5-only" not in sys.argv[3:]:
        fetch_firms(root, year, receipts)
    if "firms-only" not in sys.argv[3:]:
        fetch_era5(root, year, receipts)
    out = Path(sys.argv[1]).expanduser() / "receipts" / f"season_{year}{_suffix(sys.argv[3:])}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"authority": AUTHORITY, "files": receipts}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
