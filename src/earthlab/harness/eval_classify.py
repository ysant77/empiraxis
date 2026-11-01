"""The independent evaluator for threshold exceedance. It imports no training or feature code.

It reads the published file and stored probabilities, and rebuilds labels and the persistence
reference with the regression evaluator's parser. Accuracy is reported only next to what a
model that always says no would score. Bootstrap: 7-day moving blocks with a fixed seed.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from earthlab.forecast.evaluator import BLOCK_DAYS, RESAMPLES, SEED, reference

HOURS = 24
BINS = 10
MAX_ECE = 0.05


def labels(truth: np.ndarray, issues: np.ndarray, horizon: int, threshold: float) -> np.ndarray:
    """1, 0, or NaN when the value is missing. A missing value is never scored."""
    values = truth[issues + horizon]
    return np.where(np.isnan(values), np.nan, (values > threshold).astype(float))


def persistence_alarm(truth: np.ndarray, issues: np.ndarray, threshold: float) -> np.ndarray:
    base = reference(truth, issues)
    return np.where(np.isnan(base), np.nan, (base > threshold).astype(float))


def _counts(said: np.ndarray, y: np.ndarray) -> tuple[int, int, int, int]:
    keep = ~(np.isnan(said) | np.isnan(y))
    s, t = said[keep] > 0.5, y[keep] > 0.5
    return int((s & t).sum()), int((s & ~t).sum()), int((~s & t).sum()), int((~s & ~t).sum())


def _f1(tp: Any, fp: Any, fn: Any) -> Any:
    return 2 * tp / np.maximum(2 * tp + fp + fn, 1)


def average_precision(prob: np.ndarray, y: np.ndarray) -> float | None:
    keep = ~(np.isnan(prob) | np.isnan(y))
    p, t = prob[keep], y[keep]
    if t.sum() == 0:
        return None
    order = np.argsort(-p, kind="stable")
    hits = t[order]
    precision = np.cumsum(hits) / np.arange(1, len(hits) + 1)
    return float((precision * hits).sum() / hits.sum())


def calibration(prob: np.ndarray, y: np.ndarray) -> dict[str, float]:
    keep = ~(np.isnan(prob) | np.isnan(y))
    p, t = prob[keep], y[keep]
    slot = np.minimum((p * BINS).astype(int), BINS - 1)
    gap = 0.0
    for bin_id in range(BINS):
        mine = slot == bin_id
        if mine.any():
            gap += abs(float(p[mine].mean() - t[mine].mean())) * float(mine.mean())
    return {"brier": float(((p - t) ** 2).mean()), "ece": gap}


def score(prob: np.ndarray, cut: float, y: np.ndarray) -> dict[str, float | None]:
    """One model: fixed-cut counts and threshold-free measures."""
    said = np.where(np.isnan(prob), np.nan, (prob >= cut).astype(float))
    tp, fp, fn, tn = _counts(said, y)
    total = tp + fp + fn + tn
    return {
        "scored": float(total),
        "positives": float(tp + fn),
        "base_rate": (tp + fn) / max(total, 1),
        "accuracy": (tp + tn) / max(total, 1),
        "accuracy_of_always_no": (fp + tn) / max(total, 1),
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "f1": float(_f1(tp, fp, fn)),
        "false_alarm_rate": fp / (fp + tn) if fp + tn else None,
        "pr_auc": average_precision(prob, y),
        **calibration(prob, y),
    }


def _day_counts(said: np.ndarray, y: np.ndarray) -> np.ndarray:
    """(tp, fp, fn) per day, pooled over regions."""
    keep = ~(np.isnan(said) | np.isnan(y))
    s, t = (said > 0.5) & keep, (y > 0.5) & keep
    hits = np.stack([(s & t).sum(axis=1), (s & ~t).sum(axis=1), (~s & t).sum(axis=1)], axis=1)
    usable = len(hits) // HOURS * HOURS
    return np.asarray(hits[:usable].reshape(-1, HOURS, 3).sum(axis=1), dtype=float)


def f1_gain(mine: np.ndarray, cut: float, base: np.ndarray, y: np.ndarray) -> dict[str, float]:
    """F1 against the persistence alarm on the same hours, with 95% block limits."""
    said = np.where(np.isnan(mine), np.nan, (mine >= cut).astype(float))
    a, b = _day_counts(said, y), _day_counts(base, y)
    days = len(a)
    rng = np.random.default_rng(SEED)
    blocks = int(np.ceil(days / BLOCK_DAYS))
    starts = rng.integers(0, max(days - BLOCK_DAYS + 1, 1), size=(RESAMPLES, blocks))
    index = (starts[..., None] + np.arange(BLOCK_DAYS)).reshape(RESAMPLES, -1)[:, :days]
    sa, sb = a[index].sum(axis=1), b[index].sum(axis=1)
    gain = _f1(sa[:, 0], sa[:, 1], sa[:, 2]) - _f1(sb[:, 0], sb[:, 1], sb[:, 2])
    whole = a.sum(axis=0), b.sum(axis=0)
    point = float(_f1(*whole[0]) - _f1(*whole[1]))
    return {
        "gain": point,
        "low": float(np.percentile(gain, 2.5)),
        "high": float(np.percentile(gain, 97.5)),
    }


def failed_checks(row: dict[str, float | None], gain: dict[str, float]) -> list[str]:
    """Why a classifier is not a success, whatever its accuracy."""
    out = []
    if not row["recall"]:
        out.append("it finds no exceedance; this is the majority class")
    if (row["precision"] or 0.0) <= float(row["base_rate"] or 0.0):
        out.append("its precision does not beat the base rate")
    pr, base = row["pr_auc"], float(row["base_rate"] or 0.0)
    if pr is None or pr <= base:
        out.append("its PR area does not beat the base rate")
    if gain["low"] <= 0:
        out.append("the lower limit of its F1 gain over persistence is not above zero")
    return out
