from __future__ import annotations

import numpy as np

from earthlab.m5 import transport_b as T


def test_wind_from_direction_conventions() -> None:
    assert abs(float(T.wind_from_deg(np.array(0.0), np.array(-5.0)))) < 1e-9  # from the north
    assert abs(float(T.wind_from_deg(np.array(-5.0), np.array(0.0))) - 90.0) < 1e-9  # from the east
    assert abs(float(T.wind_from_deg(np.array(5.0), np.array(0.0))) - 270.0) < 1e-9  # from the west


def test_next_day_change_and_lead_alignment() -> None:
    pm = np.array([10.0, 20.0, 15.0])
    assert np.allclose(T.next_day_change(pm)[:2], [10.0, -5.0]) and np.isnan(
        T.next_day_change(pm)[2]
    )
    e = np.arange(5.0)
    assert np.allclose(T.lead(e, 2)[:3], [2.0, 3.0, 4.0]) and np.isnan(T.lead(e, 2)[3:]).all()


def test_pick_lead_uses_first_lag_under_limit() -> None:
    rng = np.random.default_rng(0)
    series = [rng.normal(size=58) for _ in range(5)]
    info = T.pick_lead(series)
    assert info["k"] == 2 and set(info["autocorrelation"]) == {str(k) for k in range(1, 15)}


def test_shift_null_can_reach_small_p_with_independent_season_shifts() -> None:
    rng = np.random.default_rng(1)
    xs = [rng.normal(size=58) for _ in range(5)]
    ys = [x * 2 + rng.normal(scale=0.2, size=58) for x in xs]
    assert T.shift_p(xs, ys, 999, seed=3) <= 0.002


def test_shift_p_of_noise_is_not_small() -> None:
    rng = np.random.default_rng(2)
    xs = [rng.normal(size=58) for _ in range(5)]
    ys = [rng.normal(size=58) for _ in range(5)]
    assert T.shift_p(xs, ys, 499, seed=3) > 0.05


def test_label_rules() -> None:
    good = {"lead": (0.05, 0.4), "negative_corridor": (0.02, 0.5)}
    assert T.label(0.3, 0.01, good) == "consistent_with_transport"
    assert T.label(0.3, 0.01, {**good, "lead": (-0.1, 0.4)}) == "not_distinguishable"
    assert T.label(0.3, 0.2, good) == "not_distinguishable"
    assert T.label(-0.2, 0.01, good) == "unsupported_attribution"
    assert T.label(0.3, 0.01, {}) == "not_distinguishable"
    assert T.label(float("nan"), 0.01, good) == "not_distinguishable"


def test_boot_indices_are_shared_and_in_range() -> None:
    idx = T.boot_indices([58, 58], 7, 5, seed=1)
    assert len(idx) == 5 and all(len(d[0]) == 58 and d[0].max() < 58 for d in idx)
    xs = [np.arange(58.0), np.arange(58.0)]
    draws = T.boot_rho(xs, xs, idx)
    assert np.allclose(draws, 1.0)
