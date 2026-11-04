"""The M5 model ladder: persistence, ridge, ridge with FIRMS, and trees. Protocol m5-protocol-1.

Stage P runs the published blocked scheme inside one season. Stage T trains on several
seasons and scores one held-out season. Every rung is scored on the same rows. Missing PM2.5
inputs are never set to zero: ridge takes the train mean after scaling (as the published
ablation does); trees read NaN natively.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from sklearn.ensemble import HistGradientBoostingRegressor

from earthlab.haze import ablation as A
from earthlab.m5.ladder_data import REGIONS, Season

CONFIG = yaml.safe_load(Path("config/m5/protocol-v1.yaml").read_text(encoding="utf-8"))
HIGH = float(CONFIG["elevated_threshold_ugm3"])
ALPHAS: tuple[float, ...] = tuple(float(a) for a in CONFIG["ridge_alphas"])
_SKIP = ("model", "pooled_regions", "region_one_hot")
TREE = {k: v for k, v in CONFIG["trees"].items() if k not in _SKIP}
CHAIN = (("R1", "R0"), ("R2", "R1"), ("R3a", "R1"), ("R3", "R2"), ("R3", "R3a"))
RUNGS = ("R0", "R1", "R2", "R3a", "R3")


def ridge_fit(x: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    """Ridge weights with an unpenalised intercept (same maths as the published ablation)."""
    return A._fit(x, y, alpha)


def ridge_predict(x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray, alpha: float
                  ) -> np.ndarray:  # fmt: skip
    a, b = A._scale(x_train, x_test)
    return A._apply(b, A._fit(a, y_train, alpha))


def pick_alpha(x_fit: np.ndarray, y_fit: np.ndarray, x_val: np.ndarray, y_val: np.ndarray
               ) -> float:  # fmt: skip
    """The penalty with the least MAE on the validation season. Scaling uses fit rows only."""
    keep = ~np.isnan(y_val)
    scores = {a: float(np.mean(np.abs(ridge_predict(x_fit, y_fit, x_val, a)[keep] - y_val[keep])))
              for a in ALPHAS}  # fmt: skip
    return min(scores, key=lambda a: scores[a])


def features(season: Season, region: int, rung: str) -> np.ndarray:
    lags = season.lags[region]
    return np.hstack([lags, season.fire]) if rung in ("R2", "R3") else lags


def tree_table(season: Season, rung: str) -> tuple[np.ndarray, np.ndarray]:
    """Rows of all regions stacked, with a region one-hot. Returns (X, y)."""
    xs, ys = [], []
    for r in range(REGIONS):
        onehot = np.zeros((len(season.rows), REGIONS))
        onehot[:, r] = 1.0
        xs.append(np.hstack([features(season, r, rung), onehot]))
        ys.append(season.y[r])
    return np.vstack(xs), np.concatenate(ys)


def fit_trees(x: np.ndarray, y: np.ndarray) -> HistGradientBoostingRegressor:
    keep = ~np.isnan(y)
    model = HistGradientBoostingRegressor(**TREE)
    return model.fit(x[keep], y[keep])


def concat(seasons: list[Season]) -> Season:
    """Seasons joined in time order (rows keep their own hour indexes)."""
    return Season(
        year=seasons[-1].year, rows=np.concatenate([s.rows for s in seasons]),
        y=np.hstack([s.y for s in seasons]), lags=np.concatenate([s.lags for s in seasons], axis=1),
        fire=np.vstack([s.fire for s in seasons]), days=np.concatenate([s.days for s in seasons]),
    )  # fmt: skip


def stage_t(train: list[Season], test: Season) -> dict[str, Any]:
    """Train on several seasons, score the held-out one. Returns errors and timing."""
    fit_all, val = concat(train), train[-1]
    fit_part = concat(train[:-1])
    preds: dict[str, np.ndarray] = {}
    cost: dict[str, float] = {}
    preds["R0"] = np.stack([test.lags[r][:, 0] for r in range(REGIONS)])
    for rung in ("R1", "R2"):
        t0, out = time.perf_counter(), []
        for r in range(REGIONS):
            xf, yf = features(fit_part, r, rung), fit_part.y[r]
            alpha = pick_alpha(
                xf[~np.isnan(yf)], yf[~np.isnan(yf)], features(val, r, rung), val.y[r]
            )
            xa, ya = features(fit_all, r, rung), fit_all.y[r]
            out.append(
                ridge_predict(xa[~np.isnan(ya)], ya[~np.isnan(ya)], features(test, r, rung), alpha)
            )
        preds[rung], cost[rung] = np.stack(out), time.perf_counter() - t0
    for rung, name in (("R1", "R3a"), ("R2", "R3")):
        t0 = time.perf_counter()
        model = fit_trees(*tree_table(fit_all, rung))
        x_test, _ = tree_table(test, rung)
        preds[name] = model.predict(x_test).reshape(REGIONS, -1)
        cost[name] = time.perf_counter() - t0
    return {"preds": preds, "cost_seconds": cost}


def score_rows(test: Season, preds: dict[str, np.ndarray], rungs: tuple[str, ...] = RUNGS
               ) -> dict[str, Any]:  # fmt: skip
    """Errors on the rows where the target and the newest lag exist, for every rung alike."""
    keep = ~np.isnan(test.y) & ~np.isnan(preds["R0"])
    errors = {k: (preds[k] - test.y)[keep] for k in rungs if k in preds}
    days = np.broadcast_to(test.days, test.y.shape)[keep]
    return {"errors": errors, "truth": test.y[keep], "days": days}


def strata(errs: dict[str, np.ndarray], truth: np.ndarray) -> dict[str, Any]:
    """MAE and row count per target band: below 25, 25 to 55, above 55. Exploratory: this
    breakdown was added after the first results and is not part of the protocol."""
    bands = {"lt25": truth < 25.0, "25to55": (truth >= 25.0) & (truth <= HIGH),
             "gt55": truth > HIGH}  # fmt: skip
    out: dict[str, Any] = {}
    for key, m in bands.items():
        out[key] = {"rows": int(m.sum())}
        if m.any():
            out[key].update({k: float(np.mean(np.abs(e[m]))) for k, e in errs.items()})
    return out


def summarise(scored: dict[str, Any]) -> dict[str, Any]:
    errs, truth, days = scored["errors"], scored["truth"], scored["days"]
    high = truth > HIGH
    pairs = [(n, o) for n, o in CHAIN if n in errs and o in errs]
    elevated = {f"{n}_vs_{o}": A.paired(errs[n][high], errs[o][high], days[high])
                for n, o in pairs} if high.sum() > 1 else {}  # fmt: skip
    return {
        "scored_rows": len(truth),
        "scored_days": len(np.unique(days)),
        "elevated_rows": int(high.sum()),
        "mae": {k: float(np.mean(np.abs(e))) for k, e in errs.items()},
        "bias": {k: float(np.mean(e)) for k, e in errs.items()},
        "elevated_mae": {
            k: float(np.mean(np.abs(e[high]))) if high.any() else None for k, e in errs.items()
        },
        "paired": {f"{n}_vs_{o}": A.paired(errs[n], errs[o], days) for n, o in pairs},
        "elevated_paired": elevated,
        "elevated_days": len(np.unique(days[high])),
        "exploratory_mae_by_stratum": strata(errs, truth),
    }


def label(paired: dict[str, float], elevated: dict[str, float] | None, rows: int) -> str:
    """Decision label from the protocol (Stage T)."""
    if rows < 200:
        return "insufficient_data"
    if paired["high"] < 0:
        return "worse"
    if paired["low"] <= 0:
        return "no_incremental_gain"
    if elevated is not None and elevated["skill"] < 0:
        return "mixed"
    return "supported_gain"


def stage_p(season: Season, run_tree: bool = True) -> dict[str, Any]:
    """Published blocked scheme inside one season for R0, R1, R2 (and trees)."""
    rows, pos = season.rows, np.arange(len(season.rows))
    errs: dict[str, list[float]] = {k: [] for k in RUNGS}
    truth: list[float] = []
    days: list[str] = []
    for train, test in A.folds(pos):
        trees = _fit_fold_trees(season, train, run_tree)
        for r in range(REGIONS):
            y = season.y[r]
            base = season.lags[r][test, 0]
            keep = ~np.isnan(y[test]) & ~np.isnan(base)
            preds = {"R0": base}
            for rung in ("R1", "R2"):
                preds[rung], _ = A.predict(
                    features(season, r, rung), y, rows[train], rows[test], rows
                )
            if run_tree:
                for rung, name in (("R1", "R3a"), ("R2", "R3")):
                    xt = tree_table(season, rung)[0].reshape(REGIONS, len(rows), -1)[r][test]
                    preds[name] = trees[name].predict(xt)
            for k, v in preds.items():
                errs[k] += list((v - y[test])[keep])
            truth += list(y[test][keep])
            days += list(season.days[test][keep])
    use = tuple(k for k in RUNGS if errs[k])
    return summarise({"errors": {k: np.array(errs[k]) for k in use}, "truth": np.array(truth),
                      "days": np.array(days)})  # fmt: skip


def _fit_fold_trees(season: Season, train: np.ndarray, run: bool) -> dict[str, Any]:
    if not run:
        return {}
    out = {}
    for rung, name in (("R1", "R3a"), ("R2", "R3")):
        x, y = tree_table(season, rung)
        n = len(season.rows)
        idx = np.concatenate([train + r * n for r in range(REGIONS)])
        out[name] = fit_trees(x[idx], y[idx])
    return out
