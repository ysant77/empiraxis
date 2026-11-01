"""Measure two allowlisted forecasters on one chronological split. Trusted code only.

A forecaster comes from `FORECASTERS` by exact name. No proposal can add one, and nothing
here reads files, opens a network connection or runs model-written code. The AR(1) fit is a
closed-form least-squares line on the train part of a synthetic series. This is a pilot
comparison, not autonomous training.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import NamedTuple

from earthlab.method.contracts import (
    CandidateScore,
    EvaluationPlan,
    MeasuredComparison,
    MethodKind,
)
from earthlab.method.toy import ToySeriesV1

Forecast = Callable[[float], float]


class EvaluationUndefined(ValueError):
    """The data give no defined fit or gain. The caller abstains."""


class Split(NamedTuple):
    train_end: int  # Pairs with a target index below this fit the method.
    test_start: int  # Pairs with a target index at or above this score it.


def fit_last_value(_train: Sequence[float]) -> Forecast:
    """The deterministic baseline: the next value equals the last value."""
    return lambda previous: previous


def fit_ar1(train: Sequence[float]) -> Forecast:
    """Fit y[t] = a + b * y[t-1] by ordinary least squares on the train values only."""
    xs, ys = train[:-1], train[1:]
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    spread = sum((x - mean_x) ** 2 for x in xs)
    if spread == 0:
        raise EvaluationUndefined("the train part has no variation")
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / spread
    intercept = mean_y - slope * mean_x
    return lambda previous: intercept + slope * previous


FORECASTERS: dict[str, tuple[MethodKind, Callable[[Sequence[float]], Forecast]]] = {
    "last_value": ("deterministic", fit_last_value),
    "ar1_ols": ("statistical", fit_ar1),
}


def chronological_split(length: int, plan: EvaluationPlan) -> Split:
    """Train comes first, then the embargo gap, then test. No index is ever shuffled."""
    train_end = int(length * plan.train_fraction)
    return Split(train_end, train_end + plan.embargo_steps)


def _errors(forecast: Forecast, values: Sequence[float], test_start: int) -> list[float]:
    """One-step absolute errors. Each forecast sees only the value just before its target."""
    return [abs(values[t] - forecast(values[t - 1])) for t in range(test_start, len(values))]


def _gain(baseline: Sequence[float], challenger: Sequence[float]) -> float:
    total = sum(baseline)
    if total == 0:
        raise EvaluationUndefined("the baseline error is zero, so the gain is undefined")
    return 1.0 - sum(challenger) / total


def _block_interval(
    baseline: Sequence[float], challenger: Sequence[float], plan: EvaluationPlan
) -> tuple[float, float]:
    """A moving-block bootstrap interval of the gain, with the plan's own seed."""
    n, block = len(baseline), plan.bootstrap_block
    rng = random.Random(plan.bootstrap_seed)  # noqa: S311 - reproducible, not security
    gains: list[float] = []
    for _ in range(plan.bootstrap_resamples):
        picks: list[int] = []
        while len(picks) < n:
            start = rng.randrange(n - block + 1)
            picks.extend(range(start, start + block))
        picks = picks[:n]
        base_sum = sum(baseline[i] for i in picks)
        if base_sum > 0:
            gains.append(1.0 - sum(challenger[i] for i in picks) / base_sum)
    if not gains:
        raise EvaluationUndefined("no bootstrap resample has a nonzero baseline error")
    gains.sort()
    tail = (100 - plan.ci_percent) / 200
    return gains[int(tail * (len(gains) - 1))], gains[int((1 - tail) * (len(gains) - 1))]


def measure(
    series: ToySeriesV1, plan: EvaluationPlan, baseline_id: str, challenger_id: str
) -> MeasuredComparison:
    """Fit on the train part, score on the test part, and hold the plan's gap between them."""
    values = series.values
    split = chronological_split(len(values), plan)
    train = values[: split.train_end]
    base = _errors(FORECASTERS[baseline_id][1](train), values, split.test_start)
    other = _errors(FORECASTERS[challenger_id][1](train), values, split.test_start)
    gain = _gain(base, other)
    low, high = _block_interval(base, other, plan)
    return MeasuredComparison(
        baseline=CandidateScore(candidate_id=baseline_id, mae=sum(base) / len(base)),
        challenger=CandidateScore(candidate_id=challenger_id, mae=sum(other) / len(other)),
        relative_gain=gain,
        ci_low=low,
        ci_high=high,
        train_pairs=len(train) - 1,
        train_end=split.train_end,
        test_start=split.test_start,
        test_samples=len(base),
    )
