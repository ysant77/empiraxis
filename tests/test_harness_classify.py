"""Scenario B: the same engine, with its own independent evaluator."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fake_client import ScriptedClient, call

from earthlab.forecast import samples as S
from earthlab.harness import eval_classify as ev
from earthlab.harness.classify import fit_logistic
from earthlab.harness.scenarios import run_scenario

ROOT = Path(__file__).resolve().parents[1]


def test_an_always_no_model_fails_despite_high_accuracy() -> None:
    y = np.zeros((1000, 1))
    y[:20] = 1.0
    row = ev.score(np.zeros((1000, 1)), 0.5, y)
    assert (
        row["accuracy"] == pytest.approx(0.98) and row["accuracy_of_always_no"] == row["accuracy"]
    )
    reasons = ev.failed_checks(row, {"gain": 0.0, "low": 0.0, "high": 0.0})
    assert any("majority class" in r for r in reasons)


def test_counts_and_ranking_are_right_on_a_small_case() -> None:
    y = np.array([[1.0], [1.0], [0.0], [0.0], [np.nan]])
    prob = np.array([[0.9], [0.4], [0.6], [0.1], [0.9]])
    row = ev.score(prob, 0.5, y)
    assert (row["precision"], row["recall"], row["f1"]) == (0.5, 0.5, 0.5)
    assert row["false_alarm_rate"] == 0.5 and row["scored"] == 4
    assert ev.average_precision(prob, y) == pytest.approx((1 + 2 / 3) / 2)


def test_calibration_sees_overconfidence() -> None:
    y = np.zeros((100, 1))
    assert ev.calibration(np.full((100, 1), 0.9), y)["ece"] == pytest.approx(0.9)


def test_a_label_after_the_issue_cannot_reach_the_features() -> None:
    scaled = np.arange(100.0).reshape(50, 2)
    issues = np.array([20])
    changed = scaled.copy()
    changed[19:] = -1.0
    same = S.lag_matrix(scaled, issues, 6) == S.lag_matrix(changed, issues, 6)
    assert same.all()


def test_the_logistic_fit_separates_a_plain_rule() -> None:
    x = np.linspace(-2, 2, 400)[:, None]
    weights = fit_logistic(x, (x[:, 0] > 0).astype(float), 1.0, True)
    assert weights[0] > 0 and abs(weights[1]) < 0.2


def test_the_fixed_arm_runs_on_the_real_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    done = run_scenario("pm25-exceedance", "fixed", tmp_path / "run", None)
    assert done["status"] == "awaiting_human", done["reason"]
    assert all(done["acceptance"].values())
    assert done["recommendation"]["model_id"] in ("logistic", "persistence_alarm")
    names = {row["model"] for row in done["comparison"]}
    assert names == {"persistence_alarm", "train_rate", "logistic"}


def test_the_lead_choice_sets_the_real_fit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    client = ScriptedClient(
        [
            call("review_scope", in_scope=True, note="Within the problem."),
            call("choose_method", lags=6, penalty=10.0, balanced=False, reason="Few lags."),
            call("prepare_data"),
            call("submit_note", note="Prepared."),
            call("train_models"),
            call("submit_note", note="Trained."),
            call("review_results", action="finish", reason="No reason to change it."),
            call("recommend", outcome="abstain", reason="The evaluator shows this."),
            call("forward_decision", forward_to_human=True, note="Within the criteria."),
        ]
    )
    done = run_scenario("pm25-exceedance", "team", tmp_path / "run", client)
    assert done["status"] == "awaiting_human" and done["model_changed_the_plan"]
