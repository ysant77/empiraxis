"""The 2015 haze feature ablation: B0 to B3 on blocked, expanding folds.

Protocol: docs/haze-2015-ablation-protocol.md, frozen before any fit. Each model is compared
with the one before it on the same scored rows. Scaling and the ridge penalty come from each
fold's train rows only. The penalty's inner holdout is scaled with inner-train statistics.
This is an exploratory retrospective comparison, not a forecast.
"""

from __future__ import annotations

import itertools
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from earthlab.forecast.dataset import Grid, label_at
from earthlab.haze import ablation_features as F

MODELS = ("B0", "B1", "B2", "B3")
ALPHAS = (0.1, 1.0, 10.0, 100.0, 1000.0)
BLOCKS, RESAMPLES, SEED, HIGH = 4, 2000, 7, 55.0


def folds(rows: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding origin over four blocks. No train target reaches the scored block."""
    blocks = np.array_split(rows, BLOCKS)
    out = []
    for k in range(1, BLOCKS):
        train = np.concatenate(blocks[:k])
        out.append((train[train + F.HORIZON < blocks[k][0]], blocks[k]))
    return out


def _fit(x: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    design = np.hstack([x, np.ones((len(x), 1))])
    penalty = alpha * np.eye(design.shape[1])
    penalty[-1, -1] = 0.0
    return np.asarray(np.linalg.solve(design.T @ design + penalty, design.T @ y), dtype=float)


def _apply(x: np.ndarray, w: np.ndarray) -> np.ndarray:
    return np.asarray(np.hstack([x, np.ones((len(x), 1))]) @ w, dtype=float)


def _scale(train: np.ndarray, other: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean, std = np.nanmean(train, axis=0), np.nanstd(train, axis=0)
    std = np.where(std > 0, std, 1.0)
    return (np.nan_to_num((train - mean) / std), np.nan_to_num((other - mean) / std))


def inner_split(
    x: np.ndarray, rows: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Scaled inner-train and inner-holdout rows, and their masks. The holdout is the last 20
    percent of train rows by time. Its scaler sees inner-train rows only."""
    cut = rows[int(len(rows) * 0.8)]
    inner, held = rows + F.HORIZON < cut, rows >= cut
    x_in, x_held = _scale(x[inner], x[held])
    return x_in, x_held, inner, held


def _alpha(x: np.ndarray, y: np.ndarray, rows: np.ndarray) -> float:
    """The penalty with the least MAE on the inner holdout. x is not scaled."""
    x_in, x_held, inner, held = inner_split(x, rows)
    scores = {a: float(np.mean(np.abs(_apply(x_held, _fit(x_in, y[inner], a)) - y[held])))
              for a in ALPHAS}  # fmt: skip
    return min(scores, key=lambda a: scores[a])


def predict(
    x_all: np.ndarray, y: np.ndarray, train: np.ndarray, test: np.ndarray, rows: np.ndarray
) -> tuple[np.ndarray, float]:
    """Choose the penalty inside the train rows, then refit scaling and weights on all of them."""
    pos = {r: i for i, r in enumerate(rows)}
    tr = np.array([pos[r] for r in train if not np.isnan(y[pos[r]])])
    te = np.array([pos[r] for r in test])
    alpha = _alpha(x_all[tr], y[tr], rows[tr])
    x_tr, x_te = _scale(x_all[tr], x_all[te])
    return _apply(x_te, _fit(x_tr, y[tr], alpha)), alpha


def paired(err_new: np.ndarray, err_old: np.ndarray, days: np.ndarray) -> dict[str, float]:
    """Skill of the new model against the old one, with a whole-day bootstrap interval."""
    unique = np.unique(days)
    by_day = {d: np.flatnonzero(days == d) for d in unique}
    rng = np.random.default_rng(SEED)
    draws = []
    for _ in range(RESAMPLES):
        idx = np.concatenate([by_day[d] for d in rng.choice(unique, len(unique))])
        draws.append(1 - np.abs(err_new[idx]).sum() / np.abs(err_old[idx]).sum())
    skill = 1 - np.abs(err_new).sum() / np.abs(err_old).sum()
    low, high = np.percentile(draws, [2.5, 97.5])
    return {"skill": float(skill), "low": float(low), "high": float(high)}


def run(grid: Grid, folder: Path) -> dict[str, Any]:
    """Every model on every region and fold; pooled scores; paired comparisons."""
    rows = F.issues()
    start, met = F.load_met(folder)
    firms = F.load_firms(folder / "firms")
    shared = {"B2": F.met_features(rows, start, met)}
    shared["B3"] = np.hstack([shared["B2"], F.fire_features(rows, firms)])
    pos = {r: i for i, r in enumerate(rows)}
    errors: dict[str, list[float]] = {m: [] for m in MODELS}
    truth: list[float] = []
    day: list[str] = []
    alphas: dict[str, list[float]] = {m: [] for m in MODELS[1:]}
    for region in range(5):
        y, lags = F.target(grid, rows, region), F.pm25_lags(grid, rows, region)
        groups = {
            "B1": lags,
            "B2": np.hstack([lags, shared["B2"]]),
            "B3": np.hstack([lags, shared["B3"]]),
        }
        for train, test in folds(rows):
            te = np.array([pos[r] for r in test])
            base = lags[te, 0]
            keep = ~np.isnan(y[te]) & ~np.isnan(base)
            preds = {"B0": base}
            for name, matrix in groups.items():
                preds[name], alpha = predict(matrix, y, train, test, rows)
                alphas[name].append(alpha)
            for name in MODELS:
                errors[name] += list((preds[name] - y[te])[keep])
            truth += list(y[te][keep])
            day += [f"{label_at(int(r)):%Y-%m-%d}" for r in test[keep]]
    return summarise(errors, np.array(truth), np.array(day), alphas)


def summarise(errors: dict[str, list[float]], truth: np.ndarray, day: np.ndarray,
              alphas: dict[str, list[float]]) -> dict[str, Any]:  # fmt: skip
    err = {m: np.array(v) for m, v in errors.items()}
    high = truth > HIGH
    return {
        "scored_rows": len(truth), "scored_days": len(np.unique(day)),
        "elevated_rows": int(high.sum()),
        "mae": {m: float(np.mean(np.abs(e))) for m, e in err.items()},
        "elevated_mae": {m: float(np.mean(np.abs(e[high]))) for m, e in err.items()},
        "paired": {f"{new}_vs_{old}": paired(err[new], err[old], day)
                   for old, new in itertools.pairwise(MODELS)},
        "elevated_paired": {f"{new}_vs_{old}": paired(err[new][high], err[old][high], day[high])
                            for old, new in itertools.pairwise(MODELS)},
        "alphas": {m: sorted(set(a)) for m, a in alphas.items()},
        "computed_at": datetime.now().isoformat(timespec="seconds"),
    }  # fmt: skip
