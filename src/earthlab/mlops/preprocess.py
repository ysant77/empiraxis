"""Preprocessing fitted on one train span and applied unchanged to any later row.

Inputs stop at the availability offset. Fitting refuses a span past the train end, and feature
building refuses rows past the sealed limit. A missing input is never filled silently: a row
is dropped and counted, or, when declared, it gets an explicit mask column.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from earthlab.mlops.contracts import FittedPipelineV1, Log1p, PipelineConfigV1, Span, Standardize

_HOUR, _MONTH = 2 * np.pi / 24, 2 * np.pi / 12
CALENDAR = ("hour_sin", "hour_cos", "month_sin", "month_cos")


class LeakageRefused(ValueError):
    """The step would read data its split may not use. Nothing was fitted or built."""


@dataclass(frozen=True)
class FeatureMatrix:
    x: np.ndarray
    issues: np.ndarray
    names: tuple[str, ...]
    dropped: int


def _names(config: PipelineConfigV1, columns: tuple[str, ...]) -> tuple[str, ...]:
    names = [f"{c}_lag{lag}" for lag in range(config.lags) for c in columns]
    if config.missing == "mask":
        names += [f"{name}_known" for name in list(names)]
    return (*names, *(CALENDAR if config.calendar else ()))


def _value_steps(config: PipelineConfigV1, values: np.ndarray) -> np.ndarray:
    data = values
    for step in config.steps:
        if isinstance(step, Log1p):
            if np.nanmin(data) <= -1:
                raise ValueError("log1p needs values above -1")
            data = np.log1p(data)
    return data


def fit(
    config: PipelineConfigV1,
    values: np.ndarray,
    columns: tuple[str, ...],
    span: Span,
    train_end: int,
    source_sha256: str,
) -> FittedPipelineV1:
    """The fitted state comes from the train span alone."""
    if span.last > train_end:
        raise LeakageRefused(f"the fit span ends at {span.last}, past the train end {train_end}")
    part = _value_steps(config, values[span.first : span.last + 1])
    wanted = any(isinstance(step, Standardize) for step in config.steps)
    means = np.nanmean(part, axis=0) if wanted else np.zeros(part.shape[1])
    stds = np.nanstd(part, axis=0) if wanted else np.ones(part.shape[1])
    if not np.all(stds > 1e-9):
        raise ValueError("a column has no variation in the train span")
    return FittedPipelineV1(
        config=config, source_sha256=source_sha256, columns=columns, fit_span=span,
        fit_rows=len(part), means=tuple(float(v) for v in means),
        stds=tuple(float(v) for v in stds), feature_names=_names(config, columns),
    )  # fmt: skip


def scale(fitted: FittedPipelineV1, values: np.ndarray) -> np.ndarray:
    data = _value_steps(fitted.config, values)
    return np.asarray((data - np.array(fitted.means)) / np.array(fitted.stds), dtype=float)


def invert(fitted: FittedPipelineV1, scaled: np.ndarray, column: int | None = None) -> np.ndarray:
    """Back to original units. With a column, every value belongs to that column."""
    means, stds = np.array(fitted.means), np.array(fitted.stds)
    pick = slice(None) if column is None else column
    data = scaled * stds[pick] + means[pick]
    if any(isinstance(step, Log1p) for step in fitted.config.steps):
        data = np.expm1(data)
    return np.asarray(data, dtype=float)


def _calendar(when: list[datetime]) -> np.ndarray:
    hours = np.array([w.hour for w in when]) * _HOUR
    months = np.array([w.month for w in when]) * _MONTH
    return np.stack([np.sin(hours), np.cos(hours), np.sin(months), np.cos(months)], axis=1)


def build(
    fitted: FittedPipelineV1,
    values: np.ndarray,
    issues: np.ndarray,
    limit: int,
    when: list[datetime] | None = None,
) -> FeatureMatrix:
    """Rows for these issue positions. Every input is at or before issue minus the offset."""
    config = fitted.config
    offset = config.availability_offset_hours // config.cadence_hours
    if len(issues) == 0:
        raise ValueError("there are no issue positions")
    if issues.max() - offset >= limit:
        raise LeakageRefused("an input lies at or past the sealed limit")
    earliest = issues.min() - offset - config.lags + 1
    if earliest < 0:
        raise ValueError("the lags do not fit before the first issue")
    scaled = scale(fitted, values)
    lagged = np.concatenate([scaled[issues - offset - lag] for lag in range(config.lags)], axis=1)
    known = ~np.isnan(lagged)
    if config.missing == "drop_row":
        keep = known.all(axis=1)
        x, kept = lagged[keep], issues[keep]
    else:
        keep = np.ones(len(issues), dtype=bool)
        x = np.hstack([np.where(known, lagged, 0.0), known.astype(float)])
        kept = issues
    if config.calendar:
        if when is None:
            raise ValueError("calendar features need the issue times")
        moments = [w for w, k in zip(when, keep, strict=True) if k]
        x = np.hstack([x, _calendar(moments)])
    if x.shape[1] != len(fitted.feature_names):
        raise ValueError("the feature matrix does not match the fitted schema")
    return FeatureMatrix(x, kept, fitted.feature_names, int((~keep).sum()))
