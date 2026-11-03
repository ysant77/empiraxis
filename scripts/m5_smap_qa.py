"""SMAP quality statistics over study boxes for the downloaded pilot granules.

Usage: uv run python scripts/m5_smap_qa.py DATA_ROOT
Output: docs/m5/qa/smap_qa.json. Reads local files only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from earthlab.cases.models import BoundingBox
from earthlab.m5.smap import granule_stats

BOXES = {
    "kalimantan_study_box": BoundingBox(min_lon=113.8, min_lat=-3.2, max_lon=114.8, max_lat=-2.0),
    "kalimantan_wide": BoundingBox(min_lon=112.0, min_lat=-4.5, max_lon=116.0, max_lat=-1.0),
    "sumatra_box_b": BoundingBox(min_lon=102.5, min_lat=-4.5, max_lon=106.5, max_lat=-1.0),
    "maritime_continent": BoundingBox(min_lon=95.0, min_lat=-10.0, max_lon=120.0, max_lat=10.0),
}  # fmt: skip


def main() -> int:
    root = Path(sys.argv[1]).expanduser() / "raw" / "smap-spl3smp-v009"
    out: dict[str, dict[str, list[dict[str, object]]]] = {}
    for path in sorted(root.glob("*.h5")):
        day = re.search(r"_(\d{8})_", path.name)
        assert day
        out[day.group(1)] = {name: [s.as_dict() for s in granule_stats(path, box)]
                             for name, box in BOXES.items()}  # fmt: skip
    dest = Path("docs/m5/qa/smap_qa.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(out)} granules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
