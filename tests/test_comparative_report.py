"""The comparison stays honest about what ran, and it invents no matched task."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from earthlab.harness.comparative import coverage, matched, verified_goal, workflow_of
from earthlab.harness.comparative_report import render

ROOT = Path(__file__).resolve().parents[1]
GOOD: dict[str, Any] = {
    "status": "awaiting_human", "acceptance": {"a": True}, "code_outcome": "retain_baseline",
    "recommendation": {"outcome": "retain_baseline"},
}  # fmt: skip


def row(arm: str, scenario: str, source: str = "s") -> dict[str, Any]:
    return {"arm": arm, "scenario": scenario, "source": source, "workflow": workflow_of(arm),
            "record": GOOD, "vgc": True, "status": "awaiting_human", "replayed": True}  # fmt: skip


def test_each_rule_of_verified_goal_completion_counts() -> None:
    assert verified_goal("x", GOOD, True)
    assert not verified_goal("x", GOOD, False)
    assert not verified_goal("x", {**GOOD, "status": "failed"}, True)
    assert not verified_goal("x", {**GOOD, "acceptance": {"a": False}}, True)
    assert not verified_goal("x", {**GOOD, "code_outcome": "adopt"}, True)
    assert not verified_goal("burned-area-segmentation", GOOD, True)


def test_a_scenario_counts_as_matched_only_when_every_arm_ran_it_in_one_source() -> None:
    runs = [row("F", "a"), row("S-M", "a"), row("F", "b"), row("S-M", "b", "other")]
    assert [r["scenario"] for r in matched(runs, ("F", "S-M"), "s")] == ["a"]


def test_coverage_says_when_a_workflow_did_not_run() -> None:
    runs = [row("F", "a"), row("S-M", "a")]
    assert coverage(runs)[0]["all_three"] is False


def test_the_report_names_missing_values_and_fills_every_field() -> None:
    template = (ROOT / "config" / "benchmark" / "comparative_report.md.tmpl").read_text("utf-8")
    arm = {
        "source": "benchmark screen", "workflow": "x", "runs": 1, "vgc": 1, "safe_stops": 0,
        "failed": 0, "replays_clean": 1, "median_wall_s_reached_gate": 1.0, "total_wall_s": 1.0,
        "median_model_calls": 0, "median_tokens": 0, "largest_training_rss_mb": "not measured",
    }  # fmt: skip
    report = {
        "runs": 3, "arms": [arm | {"group": g} for g in ("F", "S-M", "T-M-v1")], "coverage": [],
        "matched_screen": [], "matched_confirm": [], "selection": [], "review": {},
    }  # fmt: skip
    text = render(report, template)
    assert "$" not in text and "Review-gate validation: not measured." in text
    assert "Energy: not measured" in text
