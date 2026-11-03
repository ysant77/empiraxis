"""Experiment A statistics: lags, rho, null, Holm and labels."""

from __future__ import annotations

import numpy as np
import pytest

from earthlab.m5 import assoc

CFG = {"bootstrap_block_days": 7, "resamples": 200, "seed": 7, "min_shift_days": 14}


def test_lagged_shifts_and_pads_with_nan() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0])
    assert np.isnan(assoc.lagged(x, 2)[:2]).all() and assoc.lagged(x, 2)[2:].tolist() == [1.0, 2.0]
    assert assoc.lagged(x, 0).tolist() == x.tolist()


def test_rho_handles_missing_and_constant() -> None:
    x = np.arange(20.0)
    assert assoc.rho(x, x * 2) == pytest.approx(1.0)
    assert np.isnan(assoc.rho(np.ones(20), x))
    assert np.isnan(assoc.rho(x[:5], x[:5]))
    y = x.copy()
    y[3] = np.nan
    assert assoc.rho(x, y) == pytest.approx(1.0)


def test_holm_is_monotone_and_capped() -> None:
    adj = assoc.holm({"a": 0.01, "b": 0.04, "c": 0.5})
    assert adj["a"] == pytest.approx(0.03) and adj["b"] == pytest.approx(0.08)
    assert adj["c"] == pytest.approx(0.5) and max(adj.values()) <= 1.0


def test_strong_trend_pair_is_supported_and_noise_is_not() -> None:
    rng = np.random.default_rng(1)
    t = np.arange(58.0)
    outcome = np.sin(t / 5) * 10 + rng.normal(0, 1, 58)
    related = np.sin(t / 5) + rng.normal(0, 0.1, 58)
    res = assoc.test_pair(outcome, related, CFG)
    assert res["rho"] > 0.8 and res["n_days"] == 58
    assert assoc.label(res, 1, 0.01) == "supported_association"
    assert assoc.label(res, -1, 0.01) == "descriptive_only"  # wrong sign
    noise = assoc.test_pair(outcome, rng.normal(size=58), CFG)
    assert assoc.label(noise, 1, 0.9) == "descriptive_only"
    assert assoc.label({"rho": float("nan")}, 1, 0.0) == "insufficient_data"


def test_p_value_counts_null_at_least_as_extreme() -> None:
    null = np.array([0.1, -0.5, 0.2, np.nan])
    assert assoc.p_value(0.4, null) == pytest.approx(2 / 4)
