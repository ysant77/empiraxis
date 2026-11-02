"""The review contract rules, on the failures that review-gate-v1 and v2 recorded."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fake_client import call
from test_method_review import CASE, CONCERN, FACTS, proposal, seats

from earthlab.harness import review_contracts as rules
from earthlab.harness.method_review import (
    STRATEGY_OF,
    CritiqueV1,
    DispositionV1,
    ReviewCode,
    check_proposal,
    critique_issues,
    disposition_issues,
    run_review,
)

THIN = {**CASE, "candidates": CASE["candidates"][:1]}


def codes(value: Any, facts: Any = FACTS) -> set[ReviewCode]:
    return {f.code for f in check_proposal(value, facts)}


def critique(**test: Any) -> CritiqueV1:
    return CritiqueV1.model_validate({**CONCERN, "test": {**CONCERN["test"], **test}})


@pytest.mark.parametrize(
    ("name", "kind", "method"),
    [
        ("ridge", "regression", "ridge"), ("Persistence", "regression", "persistence"),
        ("persistence alarm", "classification", "persistence"),
        ("persistence alarm", "regression", None),
        ("Logistic Regression", "classification", "logistic"),
        ("logistic regression", "regression", None),
        ("ridge regression", "classification", None),
        ("trees-classifier", "classification", "trees_classifier"),
        ("logistic regression with 24h lags", "classification", None),
        ("random forest", "classification", None), ("neural network", "regression", None),
        ("pixel_sum_no_qa", "raster_method", None),
    ],
)  # fmt: skip
def test_an_alias_maps_only_for_a_task_with_the_same_output(
    name: str, kind: str, method: str | None
) -> None:
    assert rules.registered_name(name, STRATEGY_OF, kind) == method


def test_every_alias_names_a_registered_method() -> None:
    assert {method for method, _ in rules.ALIASES.values()} <= set(STRATEGY_OF)
    assert not {rules._key(name) for name in STRATEGY_OF} & rules.AMBIGUOUS


@pytest.mark.parametrize(
    ("name", "start"),
    [
        ("logistic regression with 24h lags", "names a feature setting (24h)"),
        ("ridge with 48 hour window", "names a feature setting (48 hour)"),
        ("lstm", "ambiguous"), ("pixel_sum_no_qa", "not a registered method"),
    ],
)  # fmt: skip
def test_a_refused_name_says_why(name: str, start: str) -> None:
    assert rules.unknown_reason(name).startswith(start)


def test_an_alias_is_mapped_and_recorded_and_free_text_is_still_refused(tmp_path: Path) -> None:
    named = {**CASE, "simplest_baseline": "persistence baseline", "candidates": [
        {"method": "Ridge Regression", "suitability": "Fits lagged tabular rows."},
        {"method": "climatology", "suitability": "Fits calendar means alone."}]}  # fmt: skip
    held, _ = seats(tmp_path, [call("propose_method", **named)])
    done = run_review(held, FACTS)
    assert done.verdict == "proceed" and done.proposal.simplest_baseline == "persistence"
    assert done.normalized == ("persistence baseline -> persistence", "Ridge Regression -> ridge")
    free = {**named, "proposed_method": "logistic regression with 24h lags"}
    held, client = seats(tmp_path, [call("propose_method", **free)])
    refused = run_review(held, FACTS)
    assert refused.verdict == "refused" and len(client.requests) == 1
    unknown = [f for f in refused.findings if f.code == ReviewCode.UNKNOWN_METHOD]
    assert unknown and "feature setting" in unknown[0].detail
    assert refused.proposal.proposed_method == "logistic regression with 24h lags"


def test_an_ambiguous_name_is_refused_with_its_reason() -> None:
    found = check_proposal(proposal(simplest_baseline="random forest"), FACTS)
    unknown = [f for f in found if f.code == ReviewCode.UNKNOWN_METHOD]
    assert unknown and unknown[0].detail.startswith("ambiguous")


def test_the_training_budget_applies_only_to_a_method_that_trains() -> None:
    no_training = replace(FACTS, budget_seconds=0.0, estimate_seconds=0.0)
    raster = proposal(proposed_method="persistence", compute_seconds=60.0)
    assert ReviewCode.OVER_BUDGET not in codes(raster, no_training)
    assert ReviewCode.OVER_BUDGET in codes(proposal(compute_seconds=60.0), no_training)
    assert ReviewCode.OVER_BUDGET in codes(proposal(compute_seconds=900.0))


@pytest.mark.parametrize(
    "samples",
    [
        "T+6 h skill on 2026-01-01 to 2026-10-01 holdout",
        "mean T+6h skill for ridge vs persistence across five regions 2023-2025",
        "the test split 2024-01-01 to 2026-10-01", "held-out test years",
    ],
)  # fmt: skip
def test_a_critique_cannot_test_on_the_sealed_period(samples: str) -> None:
    issues = critique_issues(critique(samples=samples), [], FACTS)
    assert any("sealed" in issue for issue in issues)


def test_a_validation_test_is_open() -> None:
    text = "validation years 2019 to 2023, hours above 55 ug/m3"
    assert rules.sealed_issues(text, "pm25-regression-6h") == []


def test_the_sealed_span_comes_from_the_registered_split() -> None:
    assert rules.sealed_issues("hours in 2024", "pm25-exceedance-6h")
    assert rules.sealed_issues("the 2024 fire season", "burned-area-method") == []
    assert rules.sealed_issues("the holdout months", "burned-area-method")
    assert rules.sealed_issues("hours in 2019", "unregistered-study")
    assert rules.sealed_issues("validation hours", "unregistered-study") == []


@pytest.mark.parametrize(
    ("metric", "threshold", "backed"),
    [
        ("mae", 0.2, True),  # the case's own minimum gain, same metric and unit
        ("skill", 0.0, True),  # skill 0 equals the baseline, by the evaluator's definition
        ("mae", 0.0, False),  # zero is not a criterion for an error in ug/m3
        ("skill", 0.2, False),  # the MAE gain moved to another metric
        ("mae", 18.0, False), ("mae", 26.324, False),  # invented, or a score not in the facts
        ("mae", 55.0, False),  # the event limit in ug/m3 is not an error threshold
        ("mae", 2019.0, False), ("mae", 43818.0, False),  # a year, a row count
        ("mae", 1.0, False),  # a number in the failure-condition prose
    ],
)  # fmt: skip
def test_a_critique_threshold_needs_a_typed_criterion_for_its_metric(
    metric: str, threshold: float, backed: bool
) -> None:
    case = proposal(failure_conditions=["MAE gets worse by 1.0 ug/m3 in 2019."])
    profile = FACTS.profile.model_copy(update={"usable_rows": 43818, "missing_fraction": 0.2})
    facts = replace(FACTS, profile=profile)
    value = critique(metric=metric, threshold=threshold)
    issues = critique_issues(value, [], facts, case)
    assert any("test.threshold" in issue for issue in issues) is not backed


def test_a_refused_threshold_names_the_registered_criteria() -> None:
    issues = critique_issues(critique(threshold=18.0), [], FACTS, proposal())
    assert "registered: mae 0.2 ug/m3 on validation (proposal.expected_benefit" in issues[0]


def _accept(**case: Any) -> DispositionV1:
    return DispositionV1.model_validate({
        "disposition": "accepted", "revised_case": {**CASE, **case},
        "response": "The added method removes the concern and keeps the same baseline.",
    })  # fmt: skip


def test_an_answer_cannot_move_the_success_measure() -> None:
    concern = CritiqueV1.model_validate(CONCERN)
    original = proposal(**THIN)
    moved = {"metric": "skill", "minimum_gain": 0.2, "reason": "Skill above ridge repays it."}
    found = disposition_issues(_accept(expected_benefit=moved), concern, FACTS, original)
    assert "revised_case: expected_benefit is fixed; a review cannot change it" in found
    dropped = disposition_issues(_accept(failure_conditions=["MAE gets worse."]), concern, FACTS,
                                 original)  # fmt: skip
    assert any("failure condition removed" in issue for issue in dropped)
    assert disposition_issues(_accept(), concern, FACTS, original) == []


def test_the_review_stays_one_critique_and_one_answer(tmp_path: Path) -> None:
    steps = [call("propose_method", **THIN), call("submit_critique", **CONCERN)]
    steps += [call("submit_critique", **CONCERN)] * 3
    held, client = seats(tmp_path, steps)
    done = run_review(held, FACTS)
    assert done.critic_calls == 1 and done.lead_responses == 1 and len(client.requests) == 4
