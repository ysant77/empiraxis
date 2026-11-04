"""Count M5-C events per season before any model is fitted (data description only).

Event at issue time T: any region-hour in (T+12 h, T+24 h] above the elevated threshold.
Output: docs/m5/results/m5_event_rates.json
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from earthlab.m5 import strict_json as sj
from earthlab.m5.ladder import HIGH
from earthlab.m5.ladder_data import load_open_grid, season_rows

YEARS = (2015, 2016, 2017, 2018, 2019)


def season_counts(values: np.ndarray, year: int) -> dict[str, object]:
    rows = season_rows(year)
    win = np.stack([values[rows + h] for h in range(13, 25)])  # (12, n, regions)
    observed = ~np.isnan(win).all(axis=(0, 2))
    event = (np.nan_to_num(win, nan=0.0) > HIGH).any(axis=(0, 2)) & observed
    day = rows // 24
    hit_days = np.unique(day[event])
    runs = int((np.diff(hit_days) > 1).sum() + 1) if len(hit_days) else 0
    return {
        "issues": len(rows),
        "issues_with_observed_window": int(observed.sum()),
        "events": int(event.sum()),
        "base_rate": float(event.sum() / max(observed.sum(), 1)),
        "event_days": len(hit_days),
        "episodes_gap_over_1_day": runs,
    }


def main() -> int:
    grid = load_open_grid(Path("data/nea/Historical1hrPM2.5.csv"))
    out = {
        "threshold_ugm3": HIGH,
        "years": {str(y): season_counts(grid.values, y) for y in YEARS},
    }
    Path("docs/m5/results/m5_event_rates.json").write_text(sj.dumps(out, indent=2) + "\n")
    print(sj.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
