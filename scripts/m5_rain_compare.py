"""Compare ERA5 and IMERG hourly rain over the three H1 corridors for pilot days.

Usage: uv run python scripts/m5_rain_compare.py DATA_ROOT HAZE2015_RUN_FOLDER RUN DAY...
Output: docs/m5/qa/rain_compare_<run>.json. Reads local files only.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from earthlab.haze.geometry import H1_SOURCE_BOXES, corridor
from earthlab.m5 import imerg
from earthlab.m5.rain_compare import compare, imerg_hour_ending, lag_profile


def starts(path: Path) -> datetime:
    m = re.search(r"IMERG\.(\d{8})-S(\d{6})", path.name)
    assert m
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def era5_series(extract: Path, box_id: str) -> dict[datetime, float]:
    series = next(s for s in json.loads(extract.read_text())["series"] if s["box_id"] == box_id)
    return {datetime.fromisoformat(h["time"].replace("Z", "+00:00")): h["precip_mm"]
            for h in series["hours"] if h["precip_mm"] is not None}  # fmt: skip


def main() -> int:
    data, haze, run, days = (
        Path(sys.argv[1]).expanduser(),
        Path(sys.argv[2]).expanduser(),
        sys.argv[3],
        sys.argv[4:],
    )
    files = sorted((data / "raw" / f"imerg-v07-{run}").glob("*.HDF5"))
    wanted = {d.replace("-", "") for d in days}
    files = [f for f in files if re.search(r"IMERG\.(\d{8})", f.name).group(1) in wanted]  # type: ignore[union-attr]
    out: dict[str, object] = {"run": run, "days": days, "granules": len(files)}
    for src in H1_SOURCE_BOXES:
        grids = {starts(f): imerg.read_box(f, corridor(src)) for f in files}
        era = era5_series(haze / "extract_10m.json", src.box_id)
        ends = sorted({s + timedelta(minutes=30 * k) for s in grids for k in (1, 2)})
        ends = [e for e in ends if e in era]
        a = np.array([era[e] for e in ends])
        b = np.array([imerg_hour_ending(grids, e) for e in ends])
        out[src.box_id] = compare(a, b)
        out[src.box_id]["lag_profile_era5_shift_hours"] = lag_profile(era, ends, b)  # type: ignore[index]
    dest = Path(f"docs/m5/qa/rain_compare_{run}.json")
    dest.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
