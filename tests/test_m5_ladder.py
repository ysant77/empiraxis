"""Ladder: sealed period removal, ridge parity with the published ablation, labels, tiny run."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from earthlab.forecast.dataset import index_of
from earthlab.haze import ablation as A
from earthlab.m5 import ladder as L
from earthlab.m5.ladder_data import SEALED_FROM_LABEL, Season, load_open_grid, season_rows


def test_season_may_not_reach_the_sealed_period() -> None:
    assert len(season_rows(2019)) == len(season_rows(2015))
    with pytest.raises(ValueError, match="sealed"):
        season_rows(2024)


def test_open_grid_has_no_sealed_values() -> None:
    nea = Path("data/nea/Historical1hrPM2.5.csv")
    grid = load_open_grid(nea)
    sealed = grid.values[index_of(SEALED_FROM_LABEL) :]
    assert sealed.size > 0 and np.isnan(sealed).all()
    before = grid.values[index_of(datetime(2023, 12, 1, 0)) : index_of(SEALED_FROM_LABEL)]
    assert (~np.isnan(before)).any()


def test_ridge_matches_the_published_ablation_maths() -> None:
    rng = np.random.default_rng(0)
    x, y = rng.normal(size=(60, 4)), rng.normal(size=60)
    got = L.ridge_predict(x[:40], y[:40], x[40:], 10.0)
    a, b = A._scale(x[:40], x[40:])
    assert np.allclose(got, A._apply(b, A._fit(a, y[:40], 10.0)))


def season(n: int = 300, seed: int = 0) -> Season:
    rng = np.random.default_rng(seed)
    base = np.cumsum(rng.normal(0, 1, (5, n + 60)), axis=1) + 40
    lags = np.stack([np.stack([base[r, 40 - k : 40 - k + n] for k in range(24)], axis=1)
                     for r in range(5)])  # fmt: skip
    y = base[:, 40 + 4 : 40 + 4 + n].copy()
    y[0, 5] = np.nan
    days = np.array([f"d{i // 24}" for i in range(n)])
    return Season(2015, np.arange(n, dtype=np.int64), y, lags, rng.normal(size=(n, 9)), days)


def test_stage_t_scores_all_rungs_on_the_same_rows() -> None:
    train = [season(300, 1), season(300, 2)]
    test = season(200, 3)
    out = L.stage_t(train, test)
    assert set(out["preds"]) == set(L.RUNGS) and all(v >= 0 for v in out["cost_seconds"].values())
    summary = L.summarise(L.score_rows(test, out["preds"]))
    assert summary["scored_rows"] == 5 * 200 - 1  # one row has no target
    assert set(summary["mae"]) == set(L.RUNGS)
    assert (
        "R3_vs_R2" in summary["paired"]
        and summary["exploratory_mae_by_stratum"]["lt25"]["rows"] >= 0
    )


def test_decision_labels() -> None:
    gain = {"skill": 0.1, "low": 0.02, "high": 0.2}
    assert L.label(gain, {"skill": 0.05, "low": 0, "high": 0}, 500) == "supported_gain"
    assert L.label(gain, {"skill": -0.05, "low": 0, "high": 0}, 500) == "mixed"
    assert L.label({"skill": 0.0, "low": -0.1, "high": 0.1}, None, 500) == "no_incremental_gain"
    assert L.label({"skill": -0.2, "low": -0.3, "high": -0.1}, None, 500) == "worse"
    assert L.label(gain, None, 10) == "insufficient_data"


def test_stage_p_runs_on_a_synthetic_season() -> None:
    s = season(400, 5)
    out = L.stage_p(s)
    assert out["scored_rows"] > 0 and set(out["mae"]) == set(L.RUNGS)
    assert L.stage_p(s, run_tree=False)["mae"].keys() == {"R0", "R1", "R2"}


def test_stage_p_i1_runs_with_rain_features() -> None:
    from earthlab.m5.ladder_i1 import stage_p_i1

    s = season(400, 5)
    rain = np.random.default_rng(2).gamma(1.0, 1.0, (400, 6))
    rain[:5] = np.nan
    out = stage_p_i1(s, rain)
    assert out["scored_rows"] > 0 and set(out["mae"]) == {"R0", "R1", "R2", "I1"}
    assert 0 < out["rain_features_missing_share"] < 0.05 and "I1_vs_R2" in out["paired"]


def test_stage_p_h1_runs_with_era5_features() -> None:
    from datetime import timedelta

    from earthlab.haze import ablation_features as F
    from earthlab.m5.ladder_h1 import stage_p_h1

    s = season()
    rng = np.random.default_rng(3)
    start = F.utc_of(int(s.rows[0])) - timedelta(hours=12)
    met = {}
    for box in F.BOXES:
        for level in F.LEVELS:
            for part in ("u_ms", "v_ms"):
                met[f"{box}/{level}/{part}"] = rng.normal(size=400)
        met[f"{box}/10m/precip_mm"] = rng.random(400)
    out = stage_p_h1(s, start, met)
    assert set(out["mae"]) == {"R0", "R1", "R2", "H1"} and "H1_vs_R2" in out["paired"]
