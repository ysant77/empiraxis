"""NEA PM2.5 completeness per year and region, for the open (non-sealed) years only.

Usage: uv run python scripts/m5_nea_completeness.py
Output: docs/m5/coverage/nea_completeness.csv. Years from 2024 are sealed and are not reported.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from earthlab.forecast.dataset import GRID_START, REGIONS, index_of
from earthlab.m5.ladder_data import SEALED_FROM_LABEL, load_open_grid


def main() -> int:
    grid = load_open_grid(Path("data/nea/Historical1hrPM2.5.csv"))
    out = Path("docs/m5/coverage/nea_completeness.csv")
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["year", "region", "hours_in_year_grid", "hours_with_value", "missing_fraction"])
        for year in range(GRID_START.year, SEALED_FROM_LABEL.year):
            a = max(index_of(datetime(year, 1, 1, 0)), 0)
            b = index_of(datetime(year + 1, 1, 1, 0))
            for r, name in enumerate(REGIONS):
                block = grid.values[a:b, r]
                have = int((~(block != block)).sum())
                w.writerow([year, name, len(block), have, f"{1 - have / len(block):.4f}"])
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
