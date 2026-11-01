"""The decision record refuses a forged or inconsistent state at load time."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from earthlab.method.contracts import (
    MIN_GAIN_FLOOR,
    CandidateScore,
    EvaluationPlan,
    HumanMethodApproval,
    MeasuredComparison,
    MethodCandidate,
    MethodDecisionV1,
    SuitabilityCheck,
    canonical_digest,
)
from earthlab.method.toy import series_digest, synthetic_series

PLAN = EvaluationPlan(
    train_fraction=0.6,
    embargo_steps=3,
    min_relative_gain=0.10,
    bootstrap_resamples=1000,
    bootstrap_block=7,
    bootstrap_seed=7,
    dataset_sha256="a" * 64,
)
LAST = MethodCandidate(
    candidate_id="last_value",
    kind="deterministic",
    summary="Previous value.",
    estimated_min_train_samples=1,
    estimated_compute_seconds=0.0,
)
AR1 = MethodCandidate(
    candidate_id="ar1_ols",
    kind="statistical",
    summary="One fitted lag.",
    estimated_min_train_samples=30,
    estimated_compute_seconds=0.0,
)
PASSED = SuitabilityCheck(check_id="finite_values", passed=True, observed="yes", required="yes")


def _comparison(challenger_mae: float, ci_low: float = 0.05) -> MeasuredComparison:
    return MeasuredComparison(
        baseline=CandidateScore(candidate_id="last_value", mae=1.0),
        challenger=CandidateScore(candidate_id="ar1_ols", mae=challenger_mae),
        relative_gain=1.0 - challenger_mae,
        ci_low=ci_low,
        ci_high=0.4,
        train_pairs=143,
        train_end=144,
        test_start=147,
        test_samples=93,
    )


def _fields(**over: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "task_id": "toy",
        "candidates": (LAST, AR1),
        "baseline_id": "last_value",
        "plan": PLAN,
        "plan_sha256": canonical_digest(PLAN),
        "suitability": (PASSED,),
        "comparison": _comparison(0.8),
        "outcome": "select_candidate",
        "selected_id": "ar1_ols",
        "reason_code": "gain_cleared_threshold",
        "reason": "Gain cleared the threshold.",
    }
    return fields | over


def test_a_consistent_selection_loads() -> None:
    decision = MethodDecisionV1(**_fields())
    assert decision.evidence_label == "synthetic harness"
    assert decision.human_approval.status == "pending"


def test_a_gain_below_the_plan_cannot_select_the_candidate() -> None:
    with pytest.raises(ValidationError, match="registered rule"):
        MethodDecisionV1(**_fields(comparison=_comparison(0.95)))


def test_an_unstable_gain_cannot_select_the_candidate() -> None:
    with pytest.raises(ValidationError, match="registered rule"):
        MethodDecisionV1(**_fields(comparison=_comparison(0.8, ci_low=-0.01)))


def test_keep_baseline_records_why() -> None:
    kept = {"outcome": "keep_baseline", "selected_id": "last_value"}
    below = {"reason_code": "gain_below_threshold", "comparison": _comparison(0.95)}
    assert MethodDecisionV1(**_fields(**kept, **below)).selected_id == "last_value"
    unstable = {"reason_code": "gain_not_stable", "comparison": _comparison(0.8, -0.01)}
    assert MethodDecisionV1(**_fields(**kept, **unstable)).reason_code == "gain_not_stable"


def test_a_cleared_gain_must_not_hide_behind_the_baseline() -> None:
    with pytest.raises(ValidationError, match="registered rule"):
        MethodDecisionV1(
            **_fields(
                outcome="keep_baseline",
                selected_id="last_value",
                reason_code="gain_below_threshold",
            )
        )


def test_a_gain_must_match_its_scores() -> None:
    forged = _comparison(0.95).model_copy(update={"relative_gain": 0.5})
    with pytest.raises(ValidationError, match="relative_gain"):
        MethodDecisionV1(**_fields(comparison=forged))


def test_a_changed_plan_breaks_the_digest() -> None:
    lowered = PLAN.model_copy(update={"min_relative_gain": 0.05})
    with pytest.raises(ValidationError, match="plan_sha256"):
        MethodDecisionV1(**_fields(plan=lowered))


@pytest.mark.parametrize(
    "over",
    [
        {"comparison": None},
        {"plan": None, "plan_sha256": None},
        {"suitability": ()},
        {"suitability": (PASSED.model_copy(update={"passed": False}),)},
        {"baseline_id": None},
        {"baseline_id": "ar1_ols"},
        {"candidates": (AR1,)},
    ],
)
def test_a_selection_needs_all_of_its_evidence(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        MethodDecisionV1(**_fields(**over))


def test_a_zero_baseline_error_cannot_support_a_selection() -> None:
    zero = _comparison(0.8).model_copy(
        update={"baseline": CandidateScore(candidate_id="last_value", mae=0.0)}
    )
    with pytest.raises(ValidationError, match="nonzero error"):
        MethodDecisionV1(**_fields(comparison=zero))


@pytest.mark.parametrize(
    "over",
    [
        {"selected_id": "ar1_ols"},
        {"comparison": _comparison(0.8)},
        {"reason_code": "gain_cleared_threshold"},
    ],
)
def test_an_abstention_selects_nothing(over: dict[str, Any]) -> None:
    base: dict[str, Any] = {
        "task_id": "toy",
        "outcome": "abstain",
        "reason_code": "data_unsuitable",
        "reason": "The data failed a check.",
    }
    MethodDecisionV1(**base)
    with pytest.raises(ValidationError):
        MethodDecisionV1(**(base | over))


@pytest.mark.parametrize(
    "change",
    [
        {"required": False},
        {"status": "approved"},
    ],
)
def test_a_decision_cannot_approve_itself(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        MethodDecisionV1.model_validate(_fields(human_approval=change))


def test_only_a_person_can_approve() -> None:
    with pytest.raises(ValidationError):
        HumanMethodApproval.model_validate(
            {
                "task_id": "toy",
                "decision_sha256": "a" * 64,
                "decision": "approve",
                "approver_kind": "model",
                "approver": "planner",
            }
        )


@pytest.mark.parametrize(
    "change",
    [
        {"min_relative_gain": MIN_GAIN_FLOOR - 0.01},
        {"min_relative_gain": float("nan")},
        {"embargo_steps": 0},
        {"split": "random"},
        {"metric": "r2"},
        {"train_fraction": 0.99},
        {"bootstrap_resamples": 1},
    ],
)
def test_a_plan_cannot_weaken_the_comparison(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EvaluationPlan.model_validate(PLAN.model_dump() | change)


def test_the_generator_is_reproducible() -> None:
    one = synthetic_series("synthetic-a", seed=1, phi=0.3, length=20)
    two = synthetic_series("synthetic-a", seed=1, phi=0.3, length=20)
    other = synthetic_series("synthetic-a", seed=2, phi=0.3, length=20)
    assert series_digest(one) == series_digest(two) != series_digest(other)


def test_a_toy_series_cannot_name_a_real_dataset() -> None:
    with pytest.raises(ValidationError):
        synthetic_series("nea-pm25-2015", seed=1, phi=0.3, length=5)
