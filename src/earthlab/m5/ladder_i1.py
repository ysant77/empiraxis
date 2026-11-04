"""Rung I1 (Amendment 4): ridge on lags, FIRMS and IMERG Early rain, Stage P blocks, one season.

Compared with R2 (lags and FIRMS) and R1 (lags). Rain features are visible at the issue time by
the nominal 4 h latency. A missing window is imputed with the training mean after scaling.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from earthlab.haze import ablation as A
from earthlab.haze import ablation_features as F
from earthlab.m5 import imerg_series as S
from earthlab.m5.ladder import HIGH, strata
from earthlab.m5.ladder_data import REGIONS, Season

PAIRS = (("R1", "R0"), ("R2", "R1"), ("I1", "R2"), ("I1", "R1"))


def rain_matrix(season: Season, series: S.Series) -> np.ndarray:
    issues = [F.utc_of(int(r)) for r in season.rows]
    return S.features(issues, series)


def stage_p_i1(season: Season, rain: np.ndarray) -> dict[str, Any]:
    rows, pos = season.rows, np.arange(len(season.rows))
    names = ("R0", "R1", "R2", "I1")
    errs: dict[str, list[float]] = {k: [] for k in names}
    truth: list[float] = []
    days: list[str] = []
    for train, test in A.folds(pos):
        for r in range(REGIONS):
            y, lags = season.y[r], season.lags[r]
            mats = {"R1": lags, "R2": np.hstack([lags, season.fire]),
                    "I1": np.hstack([lags, season.fire, rain])}  # fmt: skip
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
        "rain_features_missing_share": float(np.isnan(rain).mean()),
        "mae": {k: float(np.mean(np.abs(v))) for k, v in e.items()},
        "elevated_mae": {k: float(np.mean(np.abs(v[high]))) for k, v in e.items()},
        "paired": {f"{n}_vs_{o}": A.paired(e[n], e[o], d) for n, o in PAIRS},
        "elevated_paired": {
            f"{n}_vs_{o}": A.paired(e[n][high], e[o][high], d[high]) for n, o in PAIRS
        },
        "exploratory_mae_by_stratum": strata(e, t),
    }
