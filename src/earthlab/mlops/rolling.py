"""Rolling-origin selection of the ridge penalty inside the train years only.

Each fold trains on every train year before its fold year and scores that year at T+6 h. Train
issues whose target reaches the fold year are left out, so no target crosses the fold edge. The
scaler is fitted on each fold's train rows. Validation and test rows never enter a fold, so the
selection spends no validation data. Persistence is scored on the same fold rows as the baseline.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import numpy as np

from earthlab.forecast import samples as S
from earthlab.forecast.dataset import Grid, index_of
from earthlab.mlops.contracts import SearchResultV1, SearchSpaceV1
from earthlab.mlops.tuning import search

HORIZON = 6
LAGS = 24
FOLD_YEARS = (2016, 2017, 2018)
ALPHAS = (1.0, 10.0, 100.0, 1000.0, 10000.0)  # the B4 grid


def fold_rows(year: int) -> tuple[np.ndarray, np.ndarray]:
    """Train and score issue indices for one fold. Both stay inside the train split."""
    first, last = S.split_bounds("train")
    start, end = index_of(datetime(year, 1, 1)), index_of(datetime(year + 1, 1, 1)) - 1
    end = min(end, last)
    earliest = max(first, LAGS + S.USABLE_OFFSET)
    train = np.arange(earliest, start - HORIZON, dtype=np.int64)  # targets end before the fold
    score = np.arange(max(start, earliest), end - HORIZON + 1, dtype=np.int64)
    return train, score


def _fold_mae(grid: Grid, year: int, alpha: float | None) -> float:
    """T+6 h MAE on one fold. alpha None scores persistence."""
    train, score = fold_rows(year)
    truth = grid.values[score + HORIZON]
    if alpha is None:
        return float(np.nanmean(np.abs(S.persistence(grid, score) - truth)))
    mask = np.zeros(len(grid.values), dtype=bool)
    mask[: train.max() + HORIZON + 1] = True
    scaler = S.fit_scaler(grid, log=False, train_mask=mask)
    scaled = scaler.apply(grid.values)
    weights = S.fit_ridge(S.lag_matrix(scaled, train, LAGS), scaled[train + HORIZON], alpha)
    pred = scaler.invert(S.apply_ridge(S.lag_matrix(scaled, score, LAGS), weights))
    return float(np.nanmean(np.abs(pred - truth)))


def space(budget_seconds: float = 300.0) -> SearchSpaceV1:
    return SearchSpaceV1(
        method_id="lagged_ridge", metric="rolling_origin_mae_t6", direction="minimize",
        candidates=tuple({"alpha": a} for a in ALPHAS), seeds=(0,),
        budget_seconds=budget_seconds, max_memory_mb=8192.0,
    )  # fmt: skip


def run(grid: Grid, budget_seconds: float = 300.0) -> dict[str, Any]:
    """The search, each fold's scores, and persistence on the same folds."""
    folds: dict[str, dict[int, float]] = {}

    def trainer(config: Mapping[str, Any], _seed: int) -> float:
        alpha = float(config["alpha"])
        scores = {year: _fold_mae(grid, year, alpha) for year in FOLD_YEARS}
        folds[f"{alpha:g}"] = scores
        return float(np.mean(list(scores.values())))

    result: SearchResultV1 = search(space(budget_seconds), trainer)
    result = result.model_copy(update={"selection_split": "rolling_origin_train"})
    baseline = {year: _fold_mae(grid, year, None) for year in FOLD_YEARS}
    return {
        "search": result.model_dump(mode="json"),
        "fold_mae": folds,
        "persistence_fold_mae": baseline,
        "folds": {str(y): [int(v) for v in (fold_rows(y)[1][[0, -1]])] for y in FOLD_YEARS},
    }
