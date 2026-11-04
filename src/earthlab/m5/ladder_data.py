"""Season data for the M5 ladder: NEA grid with the sealed period removed, lags and FIRMS.

The NEA reader loads the whole file. This module sets every value from the sealed date on to
missing at once and checks it, so no later code can use a sealed value by mistake.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from earthlab.forecast.dataset import Grid, index_of, load_grid
from earthlab.haze import ablation_features as F

SEALED_FROM_LABEL = datetime(2024, 1, 1, 0)
REGIONS = 5
FIRST_ISSUE_MD, LAST_ISSUE_MD = (9, 4, 0), (10, 31, 17)


@dataclass(frozen=True)
class Season:
    year: int
    rows: np.ndarray  # issue-hour indexes
    y: np.ndarray  # (regions, n) target
    lags: np.ndarray  # (regions, n, 24)
    fire: np.ndarray  # (n, 9) FIRMS features, shared by regions
    days: np.ndarray  # (n,) issue-day labels for the day bootstrap


def load_open_grid(path: Path) -> Grid:
    """The NEA grid with every sealed hour set to missing."""
    grid, _ = load_grid(path)
    values = grid.values.copy()
    values[index_of(SEALED_FROM_LABEL) :] = np.nan
    assert np.isnan(values[index_of(SEALED_FROM_LABEL) :]).all()
    return Grid(values=values, source_sha256=grid.source_sha256)


def season_rows(year: int) -> np.ndarray:
    first, last = datetime(year, *FIRST_ISSUE_MD), datetime(year, *LAST_ISSUE_MD)
    if last >= SEALED_FROM_LABEL:
        raise ValueError("a season may not reach the sealed period")
    return np.arange(index_of(first), index_of(last) + 1, dtype=np.int64)


def build_season(grid: Grid, year: int, firms_folder: Path) -> Season:
    from earthlab.forecast.dataset import label_at

    rows = season_rows(year)
    firms = F.load_firms(firms_folder)
    return Season(
        year=year, rows=rows,
        y=np.stack([F.target(grid, rows, r) for r in range(REGIONS)]),
        lags=np.stack([F.pm25_lags(grid, rows, r) for r in range(REGIONS)]),
        fire=F.fire_features(rows, firms),
        days=np.array([f"{label_at(int(i)):%Y-%m-%d}" for i in rows]),
    )  # fmt: skip
