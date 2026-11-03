"""Fixed facts for the adversarial suite: one sound regression case and its measured setting.

The facts mirror the PM2.5 regression study. They are inputs to existing checks, not results.
"""

from __future__ import annotations

from typing import Any

from earthlab.harness.claims import ladder
from earthlab.harness.contracts import (
    BudgetV1,
    DatasetProfileV1,
    DecisionRecordV1,
    EvaluationReportV1,
    ExperimentPlanV1,
    ModelScore,
    SourceRef,
)
from earthlab.harness.method_review import ReviewFacts, apply_claims
from earthlab.harness.regression import PM25_PROBLEM
from earthlab.harness.strategy import assess

LEAD_CASE: dict[str, Any] = {
    "hypothesis": "A lagged ridge lowers the T+6 h MAE against persistence in all regions.",
    "proposed_method": "ridge", "simplest_baseline": "persistence",
    "candidates": [{"method": "ridge", "suitability": "Fits lagged tabular rows."},
                   {"method": "climatology", "suitability": "Fits calendar means alone."}],
    "data_sufficiency": "The train years hold enough hourly rows for a linear fit.",
    "expected_benefit": {"metric": "mae", "minimum_gain": 0.2,
                         "reason": "A smaller gain does not repay the extra pipeline."},
    "leakage_risks": ["The two hour availability latency must hold for every lag."],
    "compute_seconds": 30.0,
    "failure_conditions": ["The lower limit of MAE skill is at or below zero."],
}  # fmt: skip


def profile_with(latency_hours: int, **change: Any) -> DatasetProfileV1:
    base = DatasetProfileV1(
        sources=(SourceRef(name="nea.csv", sha256="a" * 64),), variable="pm25", unit="ug/m3",
        usable_rows=20_000, missing_fraction=0.01, labels_present=True, granularity="1 h",
        availability_latency_hours=latency_hours,
    )  # fmt: skip
    return base.model_copy(update=change)


def plan(input_offset_hours: int) -> ExperimentPlanV1:
    return ExperimentPlanV1(
        plan_id="plan-1", methods=("persistence", "climatology", "ridge"), config={"lags": 12},
        split_protocol="validation only", metrics=("mae", "skill"),
        input_offset_hours=input_offset_hours, seed=1,
        budget=BudgetV1(max_seconds=600, max_training_seconds=300, max_model_calls=10),
    )  # fmt: skip


PROFILE = profile_with(2)
FACTS = ReviewFacts(PM25_PROBLEM, PROFILE, assess(PM25_PROBLEM, PROFILE, 1200.0), plan(3), 20.0,
                    300.0)  # fmt: skip
# The S1 shape: ridge gains on all hours and loses above 55 ug/m3.
REGRESSION = EvaluationReportV1(
    evaluator="earthlab.forecast.evaluator", evaluator_sha256="a" * 64, split_scored="validation",
    reference="B0_persistence", scores=(
        ModelScore(model="B0_persistence", metrics={"mae": 5.465, "above_55_mae": 26.3},
                   passes=False),
        ModelScore(model="M_ridge", metrics={"mae": 4.65, "above_55_mae": 37.3}, low=0.138,
                   high=0.158, passes=True),
    ),
)  # fmt: skip


def decision_findings(outcome: str, limitations: list[str]) -> list[str]:
    """Subgroup failures that code adds to a decision's limitations on the S1-shaped report."""
    decision = DecisionRecordV1.model_validate({
        "outcome": outcome, "selected": "M_ridge", "reason": "Ridge lowers MAE on all hours.",
        "limitations": limitations,
    })  # fmt: skip
    claims = ladder(REGRESSION, "M_ridge")
    kept, _ = apply_claims(decision, claims)
    return [text for text in kept.limitations if text.startswith("subgroup_failure")]
