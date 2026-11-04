"""M5-C onset audit (post hoc, exploratory). Observations only; no model is fit.

Definitions: docs/m5/onset-audit/POSTHOC_ONSET_AUDIT.md (written before the computation).
Usage: uv run python scripts/m5_c_onset_audit.py data/nea/Historical1hrPM2.5.csv OUT.json
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from earthlab.digest import file_digest
from earthlab.forecast.dataset import label_at
from earthlab.haze import ablation_features as F
from earthlab.m5 import event_c as E
from earthlab.m5 import strict_json as sj
from earthlab.m5.ladder import HIGH
from earthlab.m5.ladder_data import load_open_grid, season_rows

YEAR, MIN_OBSERVED, MERGE_HOURS, MIN_EPISODE_HOURS, NEED = 2019, 20, 24, 1, 10
SENSITIVITY = {"merge_hours": (12, 24, 48, 72), "min_observed": (16, 20, 24),
               "min_episode_hours": (1, 6)}  # fmt: skip


def episodes(hot: np.ndarray, merge: int = MERGE_HOURS) -> list[tuple[int, int]]:
    """Runs of exceedance hours. Two hours join when fewer than `merge` hours lie between them."""
    idx = np.flatnonzero(hot)
    if idx.size == 0:
        return []
    out = [[int(idx[0]), int(idx[0])]]
    for i in idx[1:]:
        if i - out[-1][1] <= merge:
            out[-1][1] = int(i)
        else:
            out.append([int(i), int(i)])
    return [(a, b) for a, b in out]


def lag_state(values: np.ndarray, r: np.ndarray, min_observed: int = MIN_OBSERVED) -> np.ndarray:
    """'ongoing', 'onset' (eligible) or 'unclear', from the 24 lag hours M5-C sees."""
    lags = np.stack([values[r - F.NEWEST - k] for k in range(F.LAGS)], axis=1)
    hot_lag = (np.nan_to_num(lags, nan=0.0) > HIGH).any(axis=(1, 2))
    observed = (~np.isnan(lags)).any(axis=2).sum(axis=1)
    return np.where(hot_lag, "ongoing", np.where(observed >= min_observed, "onset", "unclear"))


def season_episodes(values: np.ndarray, rows: np.ndarray, merge: int) -> list[tuple[int, int]]:
    """Exceedance episodes (row indices) over the lag and event hours of the season."""
    hot = (np.nan_to_num(values, nan=0.0) > HIGH).any(axis=1)
    low = int(rows[0]) - F.NEWEST - F.LAGS
    span = hot[low : int(rows[-1]) + max(E.WINDOW) + 1]
    return [(a + low, b + low) for a, b in episodes(span, merge)]


def onset_episodes(
    values: np.ndarray, r: np.ndarray, y: np.ndarray, state: np.ndarray, merge: int, min_hours: int
) -> list[tuple[int, int]]:
    """Episodes whose first hour lies in the event window of an onset-eligible positive issue."""
    hot = (np.nan_to_num(values, nan=0.0) > HIGH).any(axis=1)
    eps = [e for e in season_episodes(values, r, merge) if hot[e[0] : e[1] + 1].sum() >= min_hours]
    found: set[tuple[int, int]] = set()
    for t in r[(state == "onset") & (y == 1)]:
        found |= {e for e in eps if t + min(E.WINDOW) <= e[0] <= t + max(E.WINDOW)}
    return sorted(found)


def sensitivity(values: np.ndarray, r: np.ndarray, y: np.ndarray) -> list[dict[str, Any]]:
    """Independent-onset count under each setting. A robustness check, not a selection."""
    rows = []
    for min_obs in SENSITIVITY["min_observed"]:
        state = lag_state(values, r, min_obs)
        for merge in SENSITIVITY["merge_hours"]:
            for min_hours in SENSITIVITY["min_episode_hours"]:
                found = onset_episodes(values, r, y, state, merge, min_hours)
                rows.append({"min_observed": min_obs, "merge_hours": merge,
                             "min_episode_hours": min_hours, "independent_onsets": len(found),
                             "onset_issues": int((state == "onset").sum())})  # fmt: skip
    return rows


def week_structure(r: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    weeks = [f"{label_at(int(t)).isocalendar().week:02d}" for t in r]
    events = Counter(w for w, e in zip(weeks, y.tolist(), strict=True) if e == 1)
    return {"iso_weeks": len(set(weeks)), "weeks_with_events": len(events),
            "events_per_week": dict(sorted(events.items()))}  # fmt: skip


def episode_rows(values: np.ndarray, eps: list[tuple[int, int]]) -> list[dict[str, Any]]:
    hot = (np.nan_to_num(values, nan=0.0) > HIGH).any(axis=1)
    return [{"start": f"{label_at(a):%Y-%m-%d %H:%M}", "end": f"{label_at(b):%Y-%m-%d %H:%M}",
             "span_hours": b - a + 1, "exceedance_hours": int(hot[a : b + 1].sum())}
            for a, b in eps]  # fmt: skip


def audit(csv: Path) -> dict[str, Any]:
    values = load_open_grid(csv).values
    rows = season_rows(YEAR)
    y, scored = E.event_labels(values, rows)
    r, y = rows[scored], y[scored]
    state = lag_state(values, r)
    counts = {s: {"issues": int((state == s).sum()), "events": int(y[state == s].sum())}
              for s in ("ongoing", "onset", "unclear")}  # fmt: skip
    found = onset_episodes(values, r, y, state, MERGE_HOURS, MIN_EPISODE_HOURS)
    days = np.array([f"{label_at(int(t)):%Y-%m-%d}" for t in r])
    return {
        "audit": "m5-c-onset-audit-2 (post hoc, exploratory)",
        "season": YEAR,
        "inputs": {"nea_csv_sha256": file_digest(csv)},
        "scored_issues": len(r),
        "events": int(y.sum()),
        "m5_episode_count_by_day": E.episodes(days, y),
        "by_state": counts,
        "base_rate": {
            s: (c["events"] / c["issues"] if c["issues"] else None) for s, c in counts.items()
        },
        "exceedance_episodes_in_season": episode_rows(
            values, season_episodes(values, rows, MERGE_HOURS)
        ),
        "onset_episodes_primary": episode_rows(values, found),
        "independent_onsets": len(found),
        "threshold_declared": NEED,
        "verdict": "enough independent onsets for a restricted skill estimate"
        if len(found) >= NEED
        else "insufficient independent onsets",
        "sensitivity": sensitivity(values, r, y),
        "week_structure": week_structure(r, y),
    }


if __name__ == "__main__":
    result = audit(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(sj.dumps(result, indent=1) + "\n")
    print(sys.argv[2], result["independent_onsets"], result["verdict"])
