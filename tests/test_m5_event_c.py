from __future__ import annotations

import numpy as np

from earthlab.m5 import event_c as E


def test_event_labels_use_the_12_to_24_hour_window() -> None:
    values = np.full((100, 5), 10.0)
    values[40 + 13, 2] = 80.0  # hour T+13 for issue 40
    values[60 + 12, 0] = 90.0  # hour T+12 for issue 60 is outside the window
    y, scored = E.event_labels(values, np.array([40, 60]))
    assert y.tolist() == [1.0, 0.0] and scored.all()
    values[70 : 70 + 25, :] = np.nan
    _, scored = E.event_labels(values, np.array([70]))
    assert not scored[0]


def test_partial_window_negative_is_excluded_but_observed_positive_is_kept() -> None:
    values = np.full((130, 5), 10.0)
    values[40 + 13 : 40 + 25, 3] = np.nan  # one region missing for the whole window
    values[60 + 13 : 60 + 25, 3] = np.nan
    values[60 + 20, 1] = 80.0  # an observed exceedance in the same partial window
    values[80 + 15, :] = np.nan  # one hour missing in every region
    y, scored = E.event_labels(values, np.array([40, 60, 80, 20]))
    assert scored.tolist() == [False, True, False, True]
    assert y[1] == 1.0 and y[3] == 0.0


def test_lag_matrix_has_max_and_mean_per_lag() -> None:
    values = np.arange(50 * 5, dtype=float).reshape(50, 5)
    m = E.lag_matrix(values, np.array([30]))
    assert m.shape == (1, 48)
    assert m[0, 0] == values[28].max() and m[0, 1] == values[28].mean()


def test_fold_ids_keep_weeks_together() -> None:
    weeks = np.array(["a", "a", "b", "c", "c", "d", "e", "f"])
    fold = E.fold_ids(weeks)
    for w in set(weeks.tolist()):
        assert len(set(fold[weeks == w].tolist())) == 1


def test_logit_learns_a_clean_signal_and_platt_keeps_range() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=(400, 3))
    y = (x[:, 0] + 0.2 * rng.normal(size=400) > 0).astype(float)
    p = E.Logit().fit(x[:300], y[:300]).proba(x[300:])
    assert E.brier(p, y[300:]) < 0.15
    weeks = np.array([f"w{i // 20}" for i in range(300)])
    pl = E.platt(E.out_of_fold(x[:300], y[:300], weeks), y[:300])
    cal = pl.predict_proba(E.logit_of(p))[:, 1]
    assert ((cal >= 0) & (cal <= 1)).all()


def test_abstention_and_episodes_and_label() -> None:
    p = np.array([0.05, 0.5, 0.95, 0.9])
    y = np.array([0.0, 1.0, 1.0, 0.0])
    cov = E.covered_error(p, y)
    assert cov["coverage"] == 0.75 and abs(cov["error_rate"] - 1 / 3) < 1e-9
    days = np.array(["2019-09-01", "2019-09-02", "2019-09-10", "2019-09-11"])
    assert E.episodes(days, np.ones(4)) == 2 and E.episodes(days, np.zeros(4)) == 0
    assert E.label(0.1, 0.02, 0.05) == "useful_signal"
    assert E.label(0.1, -0.02, 0.05) == "no_supported_signal"
    assert E.label(0.1, 0.02, 0.2) == "no_supported_signal"


def test_week_bootstrap_interval_orders() -> None:
    rng = np.random.default_rng(1)
    y = (rng.random(300) < 0.3).astype(float)
    weeks = np.array([f"w{i // 20}" for i in range(300)])
    base = np.full(300, y.mean())
    ci = E.week_bootstrap({"m": y * 0.9 + 0.05}, base, y, weeks, resamples=100)["m"]
    assert ci[0] <= ci[1] and ci[0] > 0
