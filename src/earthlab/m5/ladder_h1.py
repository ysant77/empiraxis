"""Rung H1 (Amendment 5): ridge on lags, FIRMS and ERA5, Stage P blocks, one season.

ERA5 is a reanalysis made later, so H1 is a hindsight diagnostic and never an issue-time claim.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from earthlab.haze import ablation as A
from earthlab.haze import ablation_features as F
from earthlab.m5.ladder import HIGH, strata
from earthlab.m5.ladder_data import REGIONS, Season

PAIRS = (("R1", "R0"), ("R2", "R1"), ("H1", "R2"), ("H1", "R1"))


def stage_p_h1(season: Season, start: datetime, met: dict[str, np.ndarray]) -> dict[str, Any]:
    era = F.met_features(season.rows, start, met)
    rows, pos = season.rows, np.arange(len(season.rows))
    names = ("R0", "R1", "R2", "H1")
    errs: dict[str, list[float]] = {k: [] for k in names}
    truth: list[float] = []
    days: list[str] = []
    for train, test in A.folds(pos):
        for r in range(REGIONS):
            y, lags = season.y[r], season.lags[r]
            mats = {"R1": lags, "R2": np.hstack([lags, season.fire]),
                    "H1": np.hstack([lags, season.fire, era])}  # fmt: skip
            base = lags[test, 0]
            keep = ~np.isnan(y[test]) & ~np.isnan(base)
            preds = {"R0": base}
            for k, m in mats.items():
                preds[k], _ = A.predict(m, y, rows[train], rows[test], rows)
            for k in names:
                errs[k] += list((preds[k] - y[test])[keep])
            truth += list(y[test][keep])
            days += list(season.days[test][keep])
    e = {k: np.array(v) for k, v in errs.items()}
    t, d = np.array(truth), np.array(days)
    high = t > HIGH
    return {
        "scored_rows": len(t),
        "elevated_rows": int(high.sum()),
        "mae": {k: float(np.mean(np.abs(v))) for k, v in e.items()},
        "elevated_mae": {k: float(np.mean(np.abs(v[high]))) for k, v in e.items()},
        "paired": {f"{n}_vs_{o}": A.paired(e[n], e[o], d) for n, o in PAIRS},
        "elevated_paired": {
            f"{n}_vs_{o}": A.paired(e[n][high], e[o][high], d[high]) for n, o in PAIRS
        },
        "exploratory_mae_by_stratum": strata(e, t),
    }
