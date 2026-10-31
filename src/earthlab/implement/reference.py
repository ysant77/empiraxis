"""Deterministic reference solutions for the implementor development tasks (arm R0).

These are the baseline the model workers are compared with, and the oracle the frozen
acceptance checks are validated against in CI. They use only the standard library.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal

SGT = timezone(timedelta(hours=8))
Convention = Literal["hour_ending", "hour_beginning"]


def wind_vector(from_deg: float, speed_ms: float) -> tuple[float, float]:
    """(u, v) of the air moving TO, from a meteorological wind-FROM bearing and a speed.

    u is eastward, v northward. A calm wind (speed 0) is (0, 0) whatever the bearing.
    """
    if not (math.isfinite(from_deg) and math.isfinite(speed_ms)) or speed_ms < 0:
        raise ValueError("bearing and speed must be finite, and speed not negative")
    if speed_ms == 0:
        return 0.0, 0.0
    rad = math.radians(from_deg)
    return -speed_ms * math.sin(rad), -speed_ms * math.cos(rad)


def downwind_bearing(from_deg: float) -> float:
    """The bearing the air moves TO, in [0, 360)."""
    if not math.isfinite(from_deg):
        raise ValueError("bearing must be finite")
    return (from_deg + 180.0) % 360.0


def nea_hour_to_utc(label: datetime, convention: Convention) -> tuple[datetime, datetime]:
    """The UTC interval a naive Singapore-time hourly label covers.

    hour_ending: the label 01:00 covers 00:00-01:00 SGT. hour_beginning: 01:00-02:00.
    """
    if label.tzinfo is not None:
        raise ValueError("NEA labels are naive Singapore local times")
    local = label.replace(tzinfo=SGT)
    start = local - timedelta(hours=1) if convention == "hour_ending" else local
    return start.astimezone(UTC), (start + timedelta(hours=1)).astimezone(UTC)


def chronological_split(
    times: Sequence[datetime], train: float, validation: float, embargo: timedelta
) -> dict[str, list[int]]:
    """Index sets in time order: train, then validation, then test.

    Samples less than `embargo` after the end of the previous part are dropped, so no
    validation or test sample sits within the embargo of a training sample.
    """
    if not (0 < train < 1 and 0 < validation < 1 and train + validation < 1):
        raise ValueError("train and validation fractions must leave room for a test part")
    if embargo < timedelta(0):
        raise ValueError("embargo cannot be negative")
    order = sorted(range(len(times)), key=lambda i: (times[i], i))
    n_train = int(len(order) * train)
    n_val = int(len(order) * (train + validation))
    parts = {"train": order[:n_train], "validation": [], "test": []}
    for name, chunk, previous in (
        ("validation", order[n_train:n_val], parts["train"]),
        ("test", order[n_val:], None),
    ):
        before = previous if previous is not None else parts["validation"] or parts["train"]
        if not before:
            parts[name] = chunk
            continue
        edge = max(times[i] for i in before) + embargo
        parts[name] = [i for i in chunk if times[i] >= edge]
    return parts


def split_leaks(
    parts: dict[str, list[int]], times: Sequence[datetime], embargo: timedelta
) -> list[str]:
    """Every way the split leaks; empty when it is clean."""
    problems = []
    seen: dict[int, str] = {}
    for name, idx in parts.items():
        for i in idx:
            if i in seen:
                problems.append(f"sample {i} is in both {seen[i]} and {name}")
            seen[i] = name
    for earlier, later in (("train", "validation"), ("validation", "test"), ("train", "test")):
        a, b = parts.get(earlier, []), parts.get(later, [])
        if a and b and min(times[i] for i in b) < max(times[i] for i in a) + embargo:
            problems.append(f"{later} starts within the embargo of {earlier}")
    return problems
