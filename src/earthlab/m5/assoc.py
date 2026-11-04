"""Experiment A: daily rank association with block bootstrap, a circular-shift null and Holm.

These are time-pattern statistics under protocol m5-protocol-1. They name no source and show
no cause. Exposures may use hindsight data (ERA5), so nothing here is a forecast.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.stats import spearmanr

Series = NDArray[np.float64]


def lagged(exposure: Series, lag: int) -> Series:
    """Exposure on day d-lag aligned to day d; the first `lag` days are missing."""
    out = np.full(len(exposure), np.nan)
    out[lag:] = exposure[: len(exposure) - lag] if lag else exposure
    return out


def rho(x: Series, y: Series) -> float:
    ok = ~np.isnan(x) & ~np.isnan(y)
    if ok.sum() < 8 or np.ptp(x[ok]) == 0 or np.ptp(y[ok]) == 0:
        return float("nan")
    return float(spearmanr(x[ok], y[ok]).statistic)


def block_bootstrap(x: Series, y: Series, block: int, resamples: int, seed: int
                    ) -> tuple[float, float]:  # fmt: skip
    """Percentile 95% interval of rho from moving blocks of days."""
    n = len(x)
    rng = np.random.default_rng(seed)
    starts_max = n - block
    draws = []
    for _ in range(resamples):
        starts = rng.integers(0, starts_max + 1, size=-(-n // block))
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        draws.append(rho(x[idx], y[idx]))
    low, high = np.nanpercentile(draws, [2.5, 97.5])
    return float(low), float(high)


def shift_null(x: Series, y: Series, min_shift: int) -> Series:
    """rho between y and x circularly shifted by every allowed amount."""
    n = len(x)
    return np.array([rho(np.roll(x, s), y) for s in range(min_shift, n - min_shift + 1)])


def p_value(observed: float, null: Series) -> float:
    null = null[~np.isnan(null)]
    return float((1 + np.sum(np.abs(null) >= abs(observed))) / (1 + len(null)))


def holm(p: dict[str, float]) -> dict[str, float]:
    """Holm-adjusted p values."""
    order = sorted(p, key=lambda k: p[k])
    m, running, out = len(order), 0.0, {}
    for i, key in enumerate(order):
        running = max(running, min(1.0, (m - i) * p[key]))
        out[key] = running
    return out


def test_pair(outcome: Series, exposure: Series, cfg: dict[str, Any]) -> dict[str, Any]:
    low, high = block_bootstrap(exposure, outcome, cfg["bootstrap_block_days"], cfg["resamples"],
                                cfg["seed"])  # fmt: skip
    r = rho(exposure, outcome)
    null = shift_null(exposure, outcome, cfg["min_shift_days"])
    return {"rho": r, "ci_low": low, "ci_high": high, "p_shift": p_value(r, null),
            "null_abs_q95": float(np.nanpercentile(np.abs(null), 95)),
            "n_days": int((~np.isnan(exposure) & ~np.isnan(outcome)).sum())}  # fmt: skip


def label(result: dict[str, Any], expected_sign: int, p_holm: float) -> str:
    """supported_association needs: interval excludes 0, expected sign, beyond the null 95%
    range and Holm p below 0.05. Otherwise descriptive_only."""
    r = result["rho"]
    if np.isnan(r):
        return "insufficient_data"
    excludes = result["ci_low"] > 0 or result["ci_high"] < 0
    beyond = abs(r) > result["null_abs_q95"]
    if excludes and np.sign(r) == expected_sign and beyond and p_holm < 0.05:
        return "supported_association"
    return "descriptive_only"
