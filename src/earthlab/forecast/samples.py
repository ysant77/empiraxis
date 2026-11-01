"""Issue-time samples under the time rule. Latency L = 1 h: the newest usable label is T - 2.

A sample belongs to a split only if its issue time and its target are both in that split.
Inputs may read earlier splits. Statistics are fitted on train only. No input is read at or
after its availability time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from earthlab.forecast.dataset import SPLITS, Grid, index_of, label_at

HORIZONS = (1, 3, 6)
PRIMARY_HORIZON = 6
LATENCY_HOURS = 1
USABLE_OFFSET = 1 + LATENCY_HOURS
PERSISTENCE_LOOKBACK = 6
Split = Literal["train", "validation", "test"]
SEALED_FROM = index_of(SPLITS["test"][0])


def split_bounds(split: Split) -> tuple[int, int]:
    start, end = SPLITS[split]
    return index_of(start), index_of(end)


def issue_times(split: Split, window: int, horizons: tuple[int, ...] = HORIZONS) -> np.ndarray:
    """Every issue index whose target stays in the split and whose window fits the file."""
    first, last = split_bounds(split)
    earliest = max(first, window + USABLE_OFFSET - 1)
    return np.arange(earliest, last - max(horizons) + 1, dtype=np.int64)


def targets(grid: Grid, issues: np.ndarray, horizons: tuple[int, ...]) -> np.ndarray:
    """Shape (samples, horizons, regions). A missing target stays NaN and is never scored."""
    return np.stack([grid.values[issues + h] for h in horizons], axis=1)


def persistence(grid: Grid, issues: np.ndarray) -> np.ndarray:
    """B0: the newest usable value per region, or NaN when the last 6 h have none."""
    out = np.full((len(issues), grid.values.shape[1]), np.nan)
    for back in range(PERSISTENCE_LOOKBACK, -1, -1):
        found = grid.values[issues - USABLE_OFFSET - back]
        out = np.where(np.isnan(found), out, found)
    return out


def _naive(grid: Grid, issues: np.ndarray, h: int, period: int) -> np.ndarray:
    steps = int(np.ceil((h + USABLE_OFFSET) / period))
    return np.asarray(grid.values[issues + h - steps * period], dtype=float)


def daily_naive(grid: Grid, issues: np.ndarray, h: int) -> np.ndarray:
    return _naive(grid, issues, h, 24)


def weekly_naive(grid: Grid, issues: np.ndarray, h: int) -> np.ndarray:
    return _naive(grid, issues, h, 168)


def _hour_month(index: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    labels = [label_at(int(i)) for i in index]
    return np.array([x.hour for x in labels]), np.array([x.month for x in labels])


def climatology_table(grid: Grid, train_end: int) -> np.ndarray:
    """B3: train-only mean by hour, month and region."""
    index = np.arange(train_end + 1)
    hours, months = _hour_month(index)
    table = np.full((24, 13, grid.values.shape[1]), np.nan)
    for hour in range(24):
        for month in range(1, 13):
            rows = grid.values[index[(hours == hour) & (months == month)]]
            if len(rows):
                table[hour, month] = np.nanmean(rows, axis=0)
    return table


def climatology(table: np.ndarray, issues: np.ndarray, h: int) -> np.ndarray:
    hours, months = _hour_month(issues + h)
    return np.asarray(table[hours, months], dtype=float)


@dataclass(frozen=True)
class Scaler:
    """Fitted on train labels only, and applied unchanged."""

    mean: np.ndarray
    std: np.ndarray
    log: bool

    def apply(self, values: np.ndarray) -> np.ndarray:
        data = np.log1p(values) if self.log else values
        return np.asarray((data - self.mean) / self.std, dtype=float)

    def invert(self, scaled: np.ndarray) -> np.ndarray:
        data = scaled * self.std + self.mean
        return np.asarray(np.expm1(data) if self.log else data, dtype=float)


def fit_scaler(grid: Grid, log: bool, train_mask: np.ndarray | None = None) -> Scaler:
    _, last = split_bounds("train")
    values = grid.values[: last + 1]
    if train_mask is not None:
        values = values[train_mask[: last + 1]]
    data = np.log1p(values) if log else values
    return Scaler(np.nanmean(data, axis=0), np.nanstd(data, axis=0), log)


def lag_matrix(scaled: np.ndarray, issues: np.ndarray, lags: int) -> np.ndarray:
    """Usable lags for one model per horizon. A missing input becomes the train mean, zero."""
    filled = np.nan_to_num(scaled, nan=0.0)
    columns = [filled[issues - USABLE_OFFSET - lag] for lag in range(lags)]
    return np.concatenate(columns, axis=1)


def fit_ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    """B4 weights, with an intercept. Rows with a missing target are left out."""
    keep = ~np.isnan(y).any(axis=1)
    design = np.hstack([x[keep], np.ones((int(keep.sum()), 1))])
    penalty = alpha * np.eye(design.shape[1])
    penalty[-1, -1] = 0.0
    return np.asarray(np.linalg.solve(design.T @ design + penalty, design.T @ y[keep]), dtype=float)


def apply_ridge(x: np.ndarray, weights: np.ndarray) -> np.ndarray:
    return np.asarray(np.hstack([x, np.ones((len(x), 1))]) @ weights, dtype=float)
