"""The validation code, on scripted replies. These tests say nothing about critic quality."""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_client import ScriptedClient, call
from test_critique_disposition import ACCEPT, OPEN
from test_method_review import CONCERN

from earthlab.harness.contracts import EvaluationReportV1, ModelScore
from earthlab.harness.regression import ELEVATED
from earthlab.harness.review_validation import (
    ReviewCase,
    ValidationFile,
    existing_decision_controls,
    load_cases,
    run_case,
)

ROOT = Path(__file__).resolve().parents[1]
PLAN = load_cases(ROOT / "config" / "benchmark" / "review_validation.yaml")


def case(name: str) -> ReviewCase:
    return next(c for c in PLAN.cases if c.id == name)


def test_the_file_covers_the_seven_requested_errors_and_two_controls() -> None:
    assert isinstance(PLAN, ValidationFile)
    assert sum(c.truth == "fault" for c in PLAN.cases) == 7
    assert sum(c.truth == "sound" for c in PLAN.cases) == 2


@pytest.mark.parametrize("name", ["era5-as-forecast", "prithvi-incompatible"])
def test_a_blocking_fault_needs_no_model(tmp_path: Path, name: str) -> None:
    client = ScriptedClient([])
    row = run_case(case(name), tmp_path, tmp_path, client)
    assert row["detected"] and row["verdict"] == "refused" and row["model_calls"] == 0


def test_a_sound_case_draws_no_critic(tmp_path: Path) -> None:
    client = ScriptedClient([])
    row = run_case(case("ridge-supported"), tmp_path, tmp_path, client)
    assert row["verdict"] == "proceed" and not row["false_objection"]


def test_a_stopped_sound_case_counts_as_a_false_objection(tmp_path: Path) -> None:
    concern = {**CONCERN, "finding": "latency_not_named"}
    client = ScriptedClient([call("submit_critique", **concern), call("answer_critique", **OPEN)])
    row = run_case(case("ridge-minor-finding"), tmp_path, tmp_path, client)
    assert row["verdict"] == "needs_revision" and row["false_objection"]


def test_a_fault_records_the_extra_calls(tmp_path: Path) -> None:
    concern = {**CONCERN, "finding": "elevated_not_tested"}
    revised = dict(PLAN_CASE := case("elevated-ignored").case.model_dump(mode="json"))  # type: ignore[union-attr]
    revised["failure_conditions"] = [*PLAN_CASE["failure_conditions"],
                                     "MAE above 55 ug/m3 is worse than persistence."]  # fmt: skip
    client = ScriptedClient([
        call("submit_critique", **concern),
        call("answer_critique", **{**ACCEPT, "revised_case": revised}),
    ])  # fmt: skip
    row = run_case(case("elevated-ignored"), tmp_path, tmp_path, client)
    assert row["detected"] and row["verdict"] == "proceed" and row["model_calls"] == 2


def test_the_off_side_reports_todays_decision_rules() -> None:
    report = EvaluationReportV1(
        evaluator="x", evaluator_sha256="a" * 64, split_scored="validation", reference="b",
        scores=(
            ModelScore(model="b", metrics={ELEVATED: 26.3}, passes=True),
            ModelScore(model="m", metrics={ELEVATED: 28.8}, passes=False),
        ),
    )  # fmt: skip
    assert existing_decision_controls(report, "m") == ["evaluator_verdict", "adopt_limited_only"]
    assert existing_decision_controls(report, "b") == []
