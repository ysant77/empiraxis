"""The independent evaluator. It reads the published file and stored predictions, nothing else.

It imports no training, feature or baseline code, and it rebuilds targets and persistence
with its own parser. A model cannot change a number here. Bootstrap: moving blocks of whole
days with 7-day blocks and a fixed seed; regions are pooled at the time-block level.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

REGIONS = 5
ORIGIN = datetime(2014, 4, 1, 1)
OFFSET = 2
LOOKBACK = 6
BLOCK_DAYS = 7
RESAMPLES = 2000
SEED = 20261101
HIGH = 55.0
JUMP = 20.0
EXCLUDE = frozenset(
    {
        "2016-03-07T00:00:00", "2016-03-07T12:00:00", "2016-04-04T00:00:00",
        "2016-04-04T10:00:00", "2018-04-24T00:00:00", "2018-04-25T00:00:00",
        "2018-08-16T02:00:00", "2018-08-16T03:00:00",
    }
)  # fmt: skip


def read_truth(path: Path) -> tuple[np.ndarray, str]:
    """Hourly values from the published CSV, and its SHA-256. Malformed labels stay missing."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    count = int((datetime(2026, 10, 1, 0) - ORIGIN).total_seconds() // 3600) + 1
    grid = np.full((count, REGIONS), np.nan)
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = csv.reader(stream)
        next(rows)
        for row in rows:
            try:
                label = datetime.strptime(row[0].strip(), "%d/%m/%Y %H:%M")
            except ValueError:
                continue
            if label.isoformat() in EXCLUDE:
                continue
            grid[int((label - ORIGIN).total_seconds() // 3600)] = [float(c) for c in row[1:6]]
    return grid, digest


def reference(truth: np.ndarray, issues: np.ndarray) -> np.ndarray:
    out = np.full((len(issues), REGIONS), np.nan)
    for back in range(LOOKBACK, -1, -1):
        found = truth[issues - OFFSET - back]
        out = np.where(np.isnan(found), out, found)
    return out


@dataclass(frozen=True)
class Scored:
    mae: float
    rmse: float
    bias: float
    skill: float
    pairs: int


def _score(pred: np.ndarray, base: np.ndarray, target: np.ndarray) -> Scored:
    keep = ~(np.isnan(pred) | np.isnan(base) | np.isnan(target))
    if not keep.any():
        return Scored(float("nan"), float("nan"), float("nan"), float("nan"), 0)
    error = pred[keep] - target[keep]
    mae = float(np.abs(error).mean())
    return Scored(
        mae=mae,
        rmse=float(np.sqrt((error**2).mean())),
        bias=float(error.mean()),
        skill=1.0 - mae / float(np.abs(base[keep] - target[keep]).mean()),
        pairs=int(keep.sum()),
    )


def _day_loss(
    error: np.ndarray, base_error: np.ndarray, issues: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    days = (issues // 24).astype(np.int64)
    days = days - days.min()
    count = int(days.max()) + 1
    model, ref = np.zeros((count, REGIONS)), np.zeros((count, REGIONS))
    for region in range(REGIONS):
        np.add.at(model[:, region], days, error[:, region])
        np.add.at(ref[:, region], days, base_error[:, region])
    return model, ref


def bootstrap(
    pred: np.ndarray, base: np.ndarray, target: np.ndarray, issues: np.ndarray
) -> dict[str, Any]:
    """95% limits of the five-region mean skill, and of each region's skill."""
    keep = ~(np.isnan(pred) | np.isnan(base) | np.isnan(target))
    error = np.where(keep, np.abs(pred - target), 0.0)
    ref = np.where(keep, np.abs(base - target), 0.0)
    model_days, base_days = _day_loss(error, ref, issues)
    days = len(model_days)
    rng = np.random.default_rng(SEED)
    blocks = int(np.ceil(days / BLOCK_DAYS))
    starts = rng.integers(0, max(days - BLOCK_DAYS + 1, 1), size=(RESAMPLES, blocks))
    index = (starts[..., None] + np.arange(BLOCK_DAYS)).reshape(RESAMPLES, -1)[:, :days]
    model_sum = model_days[index].sum(axis=1)
    base_sum = base_days[index].sum(axis=1)
    region = 1.0 - model_sum / base_sum
    mean = region.mean(axis=1)
    return {
        "mean_skill_low": float(np.percentile(mean, 2.5)),
        "mean_skill_high": float(np.percentile(mean, 97.5)),
        "region_skill_high": [float(v) for v in np.percentile(region, 97.5, axis=0)],
        "region_skill_low": [float(v) for v in np.percentile(region, 2.5, axis=0)],
    }


def exceedance(pred: np.ndarray, target: np.ndarray, threshold: float = HIGH) -> dict[str, Any]:
    """Diagnostic only, at a fixed level. This is not an alert model."""
    keep = ~(np.isnan(pred) | np.isnan(target))
    hit, real = pred[keep] > threshold, target[keep] > threshold
    both = int((hit & real).sum())
    return {
        "threshold": threshold,
        "observed": int(real.sum()),
        "flagged": int(hit.sum()),
        "precision": both / int(hit.sum()) if hit.any() else None,
        "recall": both / int(real.sum()) if real.any() else None,
    }


def evaluate(
    truth: np.ndarray,
    issues: np.ndarray,
    horizons: list[int],
    predictions: np.ndarray,
    primary: int = 6,
) -> dict[str, Any]:
    """Recompute every metric for one model from stored predictions."""
    base = reference(truth, issues)
    table: dict[str, Any] = {}
    for slot, h in enumerate(horizons):
        target, pred = truth[issues + h], predictions[:, slot]
        by_region = [_score(pred[:, r], base[:, r], target[:, r]) for r in range(REGIONS)]
        jump = np.abs(target - base) >= JUMP
        high = target > HIGH
        row: dict[str, Any] = {
            "all": _score(pred, base, target).__dict__,
            "mean_skill": float(np.mean([s.skill for s in by_region])),
            "region_mae": [s.mae for s in by_region],
            "region_skill": [s.skill for s in by_region],
            "above_55": _score(pred[high], base[high], target[high]).__dict__,
            "change_20": _score(pred[jump], base[jump], target[jump]).__dict__,
            "exceedance": exceedance(pred, target),
        }
        if h == primary:
            row["limits"] = bootstrap(pred, base, target, issues)
        table[str(h)] = row
    return table


def compare(
    truth: np.ndarray, issues: np.ndarray, first: np.ndarray, second: np.ndarray, h: int = 6
) -> dict[str, Any]:
    """Skill of one model against another, on the same samples, with 95% limits."""
    target = truth[issues + h]
    scored = _score(first, second, target)
    limits = bootstrap(first, second, target, issues)
    return {
        "skill_against_second": scored.skill,
        "low": limits["mean_skill_low"],
        "high": limits["mean_skill_high"],
        "pairs": scored.pairs,
    }
