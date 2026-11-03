"""Write the M5 year-by-year coverage inventory from CMR metadata. No data is downloaded.

Usage: uv run python scripts/m5_coverage_inventory.py
Output: docs/m5/coverage/coverage_inventory.csv and docs/m5/coverage/hls_kalimantan_cloud.csv
"""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from earthlab.cases.models import BoundingBox
from earthlab.m5 import catalogue as C

OUT = Path("docs/m5/coverage")
YEARS = range(2015, 2027)
BOXES = {
    "kalimantan_study_box": BoundingBox(min_lon=113.8, min_lat=-3.2, max_lon=114.8, max_lat=-2.0),
    "singapore_receptor": BoundingBox(min_lon=103.6, min_lat=1.15, max_lon=104.1, max_lat=1.48),
    "source_box_a_riau": BoundingBox(min_lon=100.0, min_lat=-1.5, max_lon=103.5, max_lat=2.0),
    "source_box_b_jambi_s_sumatra": BoundingBox(
        min_lon=102.5, min_lat=-4.5, max_lon=106.5, max_lat=-1.0
    ),
    "source_box_c_kalimantan": BoundingBox(min_lon=108.5, min_lat=-3.5, max_lon=115.0, max_lat=1.0),
}  # fmt: skip
GLOBAL = {"IMERG_Early", "IMERG_Late", "IMERG_Final"}


def _job(year: int) -> list[C.CoverageRow]:
    spatial = tuple(p for p in C.PRODUCTS if p[0] not in GLOBAL)
    gridded = tuple(p for p in C.PRODUCTS if p[0] in GLOBAL)
    rows = C.inventory(BOXES, [year], products=spatial)
    return rows + C.inventory({"global_grid": None}, [year], products=gridded)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = [r for part in pool.map(_job, YEARS) for r in part]
    rows.sort(key=lambda r: (r.area, r.product, r.year, r.scope))
    with (OUT / "coverage_inventory.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["area", "product", "year", "scope", "granule_hits", "nominal_expected",
                    "fraction_of_nominal"])  # fmt: skip
        for r in rows:
            w.writerow([r.area, r.product, r.year, r.scope, r.hits,
                        "" if r.expected is None else r.expected,
                        "" if r.fraction is None else f"{r.fraction:.3f}"])  # fmt: skip
    kal = BOXES["kalimantan_study_box"]
    with (OUT / "hls_kalimantan_cloud.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["product", "year", "scope", "scenes", "scenes_with_cloud_value",
                    "mean_provider_cloud_pct", "scenes_le_20pct"])  # fmt: skip
        for short in ("HLSL30", "HLSS30"):
            for year in YEARS:
                s = C.hls_cloud_summary(kal, f"{year}{C.SEASON[0]}", f"{year}{C.SEASON[1]}", short)
                w.writerow([short, year, "aug-nov", s["scenes"], s["with_cloud_value"],
                            f"{s['mean_cloud']:.1f}", s["scenes_le_20"]])  # fmt: skip
    print(f"wrote {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
