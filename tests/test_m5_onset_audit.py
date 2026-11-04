from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

from earthlab.m5 import strict_json as sj

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "m5_c_onset_audit", ROOT / "scripts/m5_c_onset_audit.py"
)
assert _spec and _spec.loader
A = importlib.util.module_from_spec(_spec)
sys.modules["m5_c_onset_audit"] = A
_spec.loader.exec_module(A)


def hot_at(*hours: int, n: int = 300) -> np.ndarray:
    values = np.full((n, 5), 10.0)
    for h in hours:
        values[h, 2] = 90.0
    return values


def test_two_exceedance_hours_join_only_when_fewer_than_24_hours_lie_between() -> None:
    hot = np.zeros(200, dtype=bool)
    hot[[10, 34]] = True  # 23 hours between: one episode
    assert A.episodes(hot) == [(10, 34)]
    hot[34] = False
    hot[35] = True  # 24 hours between: two episodes
    assert A.episodes(hot) == [(10, 10), (35, 35)]
    assert A.episodes(np.zeros(5, dtype=bool)) == []


def test_lag_state_uses_only_the_24_lag_hours_and_the_coverage_rule() -> None:
    r = np.array([100])
    quiet = hot_at()
    assert A.lag_state(quiet, r).tolist() == ["onset"]
    assert A.lag_state(hot_at(100 - 2 - 23), r).tolist() == ["ongoing"]  # oldest lag hour
    assert A.lag_state(hot_at(100 - 2 + 1), r).tolist() == ["onset"]  # newer than T-2: not seen
    assert A.lag_state(hot_at(100 - 2 - 24), r).tolist() == ["onset"]  # older than T-25
    sparse = quiet.copy()
    sparse[: 100 - 2 - 5] = np.nan  # only 5 observed lag hours
    assert A.lag_state(sparse, r).tolist() == ["unclear"]


def test_an_exceedance_inside_the_event_window_is_an_onset_only_when_no_lag_exceedance() -> None:
    r, y = np.array([100]), np.array([1.0])
    onset = hot_at(115)  # inside (T+12, T+24] and no earlier exceedance
    state = A.lag_state(onset, r)
    assert len(A.onset_episodes(onset, r, y, state, 24, 1)) == 1
    continued = hot_at(90, 115)  # earlier exceedance merges into the same episode
    state = A.lag_state(continued, r)
    assert state.tolist() == ["ongoing"]
    assert A.onset_episodes(continued, r, y, state, 24, 1) == []


def test_minimum_episode_hours_removes_short_spikes() -> None:
    r, y = np.array([100]), np.array([1.0])
    spike = hot_at(115)
    state = A.lag_state(spike, r)
    assert len(A.onset_episodes(spike, r, y, state, 24, 1)) == 1
    assert A.onset_episodes(spike, r, y, state, 24, 6) == []


def test_committed_audit_matches_a_fresh_run_and_is_strict_json() -> None:
    committed = sj.loads_strict((ROOT / "docs/m5/onset-audit/m5_c_onset_audit.json").read_text())
    fresh = A.audit(ROOT / "data/nea/Historical1hrPM2.5.csv")
    assert fresh == committed
    assert committed["scored_issues"] == sum(s["issues"] for s in committed["by_state"].values())
    assert committed["events"] == sum(s["events"] for s in committed["by_state"].values())
    assert committed["independent_onsets"] < committed["threshold_declared"]
    assert committed["verdict"] == "insufficient independent onsets"
    assert max(r["independent_onsets"] for r in committed["sensitivity"]) < 10
