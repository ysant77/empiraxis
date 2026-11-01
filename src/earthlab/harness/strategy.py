"""The bounded strategies a Lead may consider, and code's check of each against the data.

Code writes these checks from measured facts, so a model chooses only among strategies that
fit. A costlier strategy is justified only by a measured gain over the simplest one that fits.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.harness import gates
from earthlab.harness.contracts import DatasetProfileV1, ProblemSpecV1

Strategy = Literal[
    "deterministic", "statistical", "small_neural", "pretrained_transfer", "fine_tuning",
    "distillation", "abstain_or_request",
]  # fmt: skip
NEURAL_MIN_ROWS = 10_000
STATISTICAL_MIN_ROWS = 1_000
MIN_NEURAL_SECONDS = 60.0


class StrategyCheck(Strict):
    strategy: Strategy
    eligible: bool
    reasons: tuple[str, ...] = ()


class SuitabilityFacts(Strict):
    kind: str
    rows: int
    labels_with_provenance: bool
    positive_rate: float | None
    availability_latency_hours: int
    training_budget_seconds: float
    repeated_inference_per_day: int
    pretrained_assets_approved: tuple[str, ...]
    evaluable: bool


class SuitabilityReportV1(Strict):
    schema_version: Literal["1"] = "1"
    facts: SuitabilityFacts
    checks: tuple[StrategyCheck, ...] = Field(min_length=7, max_length=7)

    def eligible(self) -> list[str]:
        return [c.strategy for c in self.checks if c.eligible]


def _check(name: Strategy, *blocks: tuple[bool, str]) -> StrategyCheck:
    reasons = tuple(text for failed, text in blocks if failed)
    return StrategyCheck(strategy=name, eligible=not reasons, reasons=reasons)


def assess(
    problem: ProblemSpecV1, profile: DatasetProfileV1, budget_seconds: float,
    pretrained: tuple[str, ...] = (),
) -> SuitabilityReportV1:  # fmt: skip
    """One row per strategy. Abstention and a resource request are always open."""
    raster = problem.kind == "raster_method"
    rows, labels = profile.usable_rows, profile.labels_present
    workload = problem.repeated_inference_per_day
    no_asset = not pretrained
    bad_inputs = raster and bool(gates.check_segmentation(profile))
    series = "no approved pretrained model fits a tabular series"
    pre_note = "the inputs and reference masks do not fit" if raster else series
    facts = SuitabilityFacts(
        kind=problem.kind, rows=rows, labels_with_provenance=labels,
        positive_rate=profile.positive_rate,
        availability_latency_hours=profile.availability_latency_hours,
        training_budget_seconds=budget_seconds, repeated_inference_per_day=workload,
        pretrained_assets_approved=pretrained, evaluable=labels or raster,
    )  # fmt: skip
    trainable = (raster, "this problem has nothing to fit")
    checks = (
        _check("deterministic"),
        _check(
            "statistical", trainable, (not labels, "no labels"),
            (rows < STATISTICAL_MIN_ROWS, f"only {rows} rows"),
        ),
        _check(
            "small_neural", trainable, (not labels, "no labels"),
            (rows < NEURAL_MIN_ROWS, f"only {rows} rows"),
            (budget_seconds < MIN_NEURAL_SECONDS, "the training budget is too small"),
            (problem.kind == "classification", "the classical model must fail first"),
        ),
        _check(
            "pretrained_transfer", (no_asset, "no approved weights"), (bad_inputs or not raster,
            pre_note),
        ),
        _check(
            "fine_tuning", (no_asset, "no approved weights"), (bad_inputs or not raster, pre_note),
            (not labels, "no labels"),
        ),
        _check(
            "distillation", trainable, (workload <= 0, "no repeated inference workload declared"),
        ),
        _check("abstain_or_request"),
    )  # fmt: skip
    return SuitabilityReportV1(facts=facts, checks=checks)


def distillation_break_even(
    teacher_train_s: float,
    student_train_s: float,
    direct_train_s: float,
    teacher_s_per_1k: float,
    student_s_per_1k: float,
) -> dict[str, float | None]:
    """Predictions needed before distillation repays its extra training.

    Against serving the teacher, the student must save its own training time. Against a direct
    student of the same size, serving costs the same, so the extra cost buys accuracy only.
    """
    saved = teacher_s_per_1k - student_s_per_1k
    extra = teacher_train_s + student_train_s - direct_train_s
    return {
        "extra_training_seconds_over_direct": round(extra, 1),
        "predictions_to_repay_student_against_teacher": (
            round(student_train_s / saved * 1000) if saved > 0 else None
        ),
        "teacher_seconds_per_1000": round(teacher_s_per_1k, 4),
        "student_seconds_per_1000": round(student_s_per_1k, 4),
    }
