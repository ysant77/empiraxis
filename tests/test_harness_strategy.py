"""Which strategies fit, from measured facts, and what distillation really costs."""

from __future__ import annotations

from earthlab.harness.contracts import DatasetProfileV1, SourceRef
from earthlab.harness.raster import BURN_PROBLEM
from earthlab.harness.regression import PM25_PROBLEM
from earthlab.harness.strategy import assess, distillation_break_even

SERIES = DatasetProfileV1(
    sources=(SourceRef(name="pm25.csv", sha256="a" * 64),), variable="pm25", unit="ug/m3",
    usable_rows=100000, missing_fraction=0.0, labels_present=True, granularity="1 h",
)  # fmt: skip
RASTER = DatasetProfileV1(
    sources=(SourceRef(name="m.tif", sha256="a" * 64),), variable="burned_area", unit="ha",
    usable_rows=1000, missing_fraction=0.0, labels_present=True, granularity="monthly",
    resolution_m=500.0, bands=("burn_date", "qa"), label_provenance="MCD64A1 QA",
)  # fmt: skip


def test_a_series_allows_no_pretrained_path_and_no_idle_distillation() -> None:
    report = assess(PM25_PROBLEM, SERIES, 1200.0)
    assert report.eligible() == [
        "deterministic", "statistical", "small_neural", "abstain_or_request"
    ]  # fmt: skip
    busy = PM25_PROBLEM.model_copy(update={"repeated_inference_per_day": 24})
    assert "distillation" in assess(busy, SERIES, 1200.0).eligible()


def test_a_raster_problem_leaves_only_the_method_or_a_request() -> None:
    report = assess(BURN_PROBLEM, RASTER, 1200.0)
    assert report.eligible() == ["deterministic", "abstain_or_request"]


def test_little_data_or_budget_blocks_a_neural_model() -> None:
    thin = SERIES.model_copy(update={"usable_rows": 5000})
    assert "small_neural" not in assess(PM25_PROBLEM, thin, 1200.0).eligible()
    assert "small_neural" not in assess(PM25_PROBLEM, SERIES, 30.0).eligible()


def test_distillation_counts_the_teacher_and_the_serving_saving() -> None:
    out = distillation_break_even(300.0, 15.0, 13.0, 0.5, 0.01)
    assert out["extra_training_seconds_over_direct"] == 302.0
    assert out["predictions_to_repay_student_against_teacher"] == round(15.0 / 0.49 * 1000)
    idle = distillation_break_even(1, 1, 1, 0.1, 0.1)
    assert idle["predictions_to_repay_student_against_teacher"] is None
