"""Declared steps between a model's raw output and the values the evaluator scores.

Thresholds and calibration come from validation data, and the record says so. Warnings report
a missing input or an input far outside the train range. They never change a value.
"""

from __future__ import annotations

import numpy as np

from earthlab.mlops import preprocess
from earthlab.mlops.contracts import FittedPipelineV1, PostprocessV1

OOD_LIMIT = 6.0
NEWTON_STEPS = 25


def _log_odds(prob: np.ndarray) -> np.ndarray:
    clipped = np.clip(prob, 1e-6, 1 - 1e-6)
    return np.asarray(np.log(clipped / (1 - clipped)), dtype=float)


def fit_calibration(prob: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Slope and intercept on the log odds, by Newton steps on the validation samples."""
    keep = ~np.isnan(y) & ~np.isnan(prob)
    score, target = _log_odds(prob[keep]), y[keep]
    if target.min() == target.max():
        raise ValueError("calibration needs both classes in the validation samples")
    design = np.stack([score, np.ones(len(score))], axis=1)
    weights = np.array([1.0, 0.0])
    for _ in range(NEWTON_STEPS):
        p = 1 / (1 + np.exp(-np.clip(design @ weights, -30, 30)))
        curve = (design.T * np.maximum(p * (1 - p), 1e-6)) @ design + 1e-6 * np.eye(2)
        weights -= np.linalg.solve(curve, design.T @ (p - target))
    return float(weights[0]), float(weights[1])


def best_cut(prob: np.ndarray, y: np.ndarray) -> float:
    """The cut with the best F1 on validation samples. All-positive output gets no credit."""
    keep = ~np.isnan(y) & ~np.isnan(prob)
    p, t = prob[keep], y[keep] > 0.5
    cuts = np.linspace(0.02, 0.98, 49)
    said = p[:, None] >= cuts
    hits = (said & t[:, None]).sum(axis=0)
    f1 = 2 * hits / np.maximum(said.sum(axis=0) + t.sum(), 1)
    f1[said.all(axis=0) | ~said.any(axis=0)] = -1.0
    return round(float(cuts[int(np.argmax(f1))]), 2)


def regression(fitted: FittedPipelineV1, post: PostprocessV1, raw: np.ndarray) -> np.ndarray:
    out = preprocess.invert(fitted, raw) if post.invert_scaling else raw
    return np.maximum(out, 0.0) if post.clip_nonnegative else out


def classification(post: PostprocessV1, raw: np.ndarray) -> np.ndarray:
    """Calibrated probabilities, or alarms when a cut is declared."""
    prob = raw
    if post.calibration is not None:
        slope, intercept = post.calibration
        prob = 1 / (1 + np.exp(-np.clip(slope * _log_odds(raw) + intercept, -30, 30)))
    if post.alarm_cut is None:
        return np.asarray(prob, dtype=float)
    return np.asarray(prob >= post.alarm_cut, dtype=float)


def input_warnings(x: np.ndarray, names: tuple[str, ...]) -> list[list[str]]:
    """One warning list per row. The inputs are scaled, so the limit is in train deviations."""
    rows: list[list[str]] = []
    data = np.abs(x)
    for row in data:
        wide = [names[int(i)] for i in np.flatnonzero(row > OOD_LIMIT)[:3]]
        rows.append([f"outside the train range: {', '.join(wide)}"] if wide else [])
    return rows
