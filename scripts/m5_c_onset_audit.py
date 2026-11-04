"""M5-C onset audit (post hoc, exploratory). Observations only; no model is fit.

Definitions: docs/m5/onset-audit/POSTHOC_ONSET_AUDIT.md (written before the computation).
Usage: uv run python scripts/m5_c_onset_audit.py data/nea/Historical1hrPM2.5.csv
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from earthlab.forecast.dataset import label_at
from earthlab.haze import ablation_features as F
from earthlab.m5 import event_c as E
from earthlab.m5.ladder import HIGH
from earthlab.m5.ladder_data import load_open_grid, season_rows

YEAR, MIN_OBSERVED, MERGE_HOURS, NEED = 2019, 20, 24, 10


def episodes(hot: np.ndarray) -> list[tuple[int, int]]:
    """Runs of exceedance hours; runs closer than MERGE_HOURS merge."""
    idx = np.flatnonzero(hot)
    if idx.size == 0:
        return []
    out = [[int(idx[0]), int(idx[0])]]
    for i in idx[1:]:
        if i - out[-1][1] <= MERGE_HOURS:
            out[-1][1] = int(i)
        else:
            out.append([int(i), int(i)])
    return [(a, b) for a, b in out]


def main() -> None:
    values = load_open_grid(Path(sys.argv[1])).values
    rows = season_rows(YEAR)
    y, scored = E.event_labels(values, rows)
    r, y = rows[scored], y[scored]
    lags = np.stack([values[r - F.NEWEST - k] for k in range(F.LAGS)], axis=1)  # (n, 24, regions)
    hot_lag = (np.nan_to_num(lags, nan=0.0) > HIGH).any(axis=(1, 2))
    observed = (~np.isnan(lags)).any(axis=2).sum(axis=1)
    state = np.where(hot_lag, "ongoing", np.where(observed >= MIN_OBSERVED, "onset", "unclear"))
    hot = (np.nan_to_num(values, nan=0.0) > HIGH).any(axis=1)
    span = slice(int(rows[0]) - F.NEWEST - F.LAGS, int(rows[-1]) + max(E.WINDOW) + 1)
    eps = [(a + span.start, b + span.start) for a, b in episodes(hot[span])]
    onset_eps = set()
    for t in r[(state == "onset") & (y == 1)]:
        lo, hi = t + min(E.WINDOW), t + max(E.WINDOW)
        onset_eps |= {e for e in eps if lo <= e[0] <= hi}
    counts = {
        s: {"issues": int((state == s).sum()), "events": int(y[state == s].sum())}
        for s in ("ongoing", "onset", "unclear")
    }
    out = {
        "audit": "m5-c-onset-audit-1 (post hoc, exploratory)",
        "season": YEAR,
        "scored_issues": len(r),
        "events": int(y.sum()),
        "m5_episode_count_by_day": E.episodes(
            np.array([f"{label_at(int(t)):%Y-%m-%d}" for t in r]), y
        ),
        "by_state": counts,
        "base_rate": {
            s: (c["events"] / c["issues"] if c["issues"] else None) for s, c in counts.items()
        },
        "exceedance_episodes_in_season": [
            {
                "start": f"{label_at(a):%Y-%m-%d %H:%M}",
                "end": f"{label_at(b):%Y-%m-%d %H:%M}",
                "hours": b - a + 1,
            }
            for a, b in eps
        ],
        "independent_onsets": len(onset_eps),
        "threshold_declared": NEED,
        "verdict": "enough independent onsets for a restricted skill estimate"
        if len(onset_eps) >= NEED
        else "insufficient independent onsets",
    }
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
