"""Frozen acceptance checks for the implementor development tasks.

Every competing worker's module is held to these same checks. They are written against
the target function names only, never against the reference code. The catalogue pins
this file's SHA-256, so any edit is visible and must be re-frozen deliberately.

The checks call the module they are given. In CI that is only the reference module. A
worker's module is run only by the trusted isolated runner (docs/implementor-runner.md),
never in the process that called the model.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import ModuleType


class AcceptanceFailure(AssertionError):
    """A check did not hold."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _raises(fn: Callable[[], object], kind: type[Exception]) -> bool:
    try:
        fn()
    except kind:
        return True
    return False


def _close(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return all(math.isclose(x, y, abs_tol=1e-9) for x, y in zip(a, b, strict=True))


def check_wind_vector(m: ModuleType) -> None:
    """Wind FROM the north moves air south; east-west signs; wrap; calm; bad input."""
    _require(_close(m.wind_vector(0.0, 10.0), (0.0, -10.0)), "north wind must blow south")
    _require(_close(m.wind_vector(90.0, 4.0), (-4.0, 0.0)), "east wind must blow west")
    _require(_close(m.wind_vector(270.0, 4.0), (4.0, 0.0)), "west wind must blow east")
    _require(_close(m.wind_vector(359.999999999, 1.0), m.wind_vector(0.0, 1.0)), "north wrap")
    _require(_close(m.wind_vector(123.0, 0.0), (0.0, 0.0)), "calm wind has no vector")
    u, v = m.wind_vector(225.0, 2.0)
    _require(math.isclose(math.hypot(u, v), 2.0), "vector length must equal the speed")
    _require(u > 0 and v > 0, "south-west wind must blow north-east")
    _require(_raises(lambda: m.wind_vector(10.0, -1.0), ValueError), "negative speed")
    _require(_raises(lambda: m.wind_vector(math.nan, 1.0), ValueError), "non-finite bearing")
    _require(m.downwind_bearing(0.0) == 180.0, "downwind of a north wind is 180")
    _require(m.downwind_bearing(270.0) == 90.0, "downwind of a west wind is 90")
    _require(0.0 <= m.downwind_bearing(180.0) < 360.0, "bearings stay in [0, 360)")


def check_nea_hour_to_utc(m: ModuleType) -> None:
    """Singapore is UTC+8 with no daylight saving; the two hour conventions differ by one."""
    label = datetime(2015, 9, 24, 1, 0)
    start, end = m.nea_hour_to_utc(label, "hour_ending")
    _require(start == datetime(2015, 9, 23, 16, 0, tzinfo=UTC), "hour ending 01:00 SGT")
    _require(end - start == timedelta(hours=1), "an hourly label covers one hour")
    begin, _ = m.nea_hour_to_utc(label, "hour_beginning")
    _require(begin == datetime(2015, 9, 23, 17, 0, tzinfo=UTC), "hour beginning 01:00 SGT")
    _require(start.utcoffset() == timedelta(0), "results are in UTC")
    new_year = m.nea_hour_to_utc(datetime(2016, 1, 1, 0, 0), "hour_ending")[0]
    _require(new_year == datetime(2015, 12, 31, 15, 0, tzinfo=UTC), "year boundary")
    aware = datetime(2015, 9, 24, 1, 0, tzinfo=UTC)
    _require(_raises(lambda: m.nea_hour_to_utc(aware, "hour_ending"), ValueError), "aware label")


def _hours(n: int, shuffle: bool = False) -> list[datetime]:
    base = datetime(2015, 9, 1)
    times = [base + timedelta(hours=i) for i in range(n)]
    return times[::-1] if shuffle else times


def check_chronological_split(m: ModuleType) -> None:
    """Time order, no overlap, embargo kept, unsorted input, and a detector that works."""
    embargo = timedelta(hours=6)
    for times in (_hours(200), _hours(200, shuffle=True)):
        parts = m.chronological_split(times, 0.6, 0.2, embargo)
        _require(set(parts) == {"train", "validation", "test"}, "three named parts")
        _require(all(parts.values()), "no part is empty on two hundred samples")
        _require(m.split_leaks(parts, times, embargo) == [], "a clean split has no leak")
        last_train = max(times[i] for i in parts["train"])
        first_val = min(times[i] for i in parts["validation"])
        _require(first_val >= last_train + embargo, "validation starts after the embargo")
        _require(len(parts["train"]) == 120, "train holds sixty percent of samples")
    times = _hours(50)
    mixed = {"train": [0, 1, 30], "validation": [10, 11], "test": [40]}
    _require(m.split_leaks(mixed, times, embargo) != [], "detects a random-split leak")
    shared = {"train": [0, 1], "validation": [1, 20], "test": [40]}
    _require(m.split_leaks(shared, times, embargo) != [], "detects a shared sample")
    _require(
        _raises(lambda: m.chronological_split(times, 0.9, 0.2, embargo), ValueError),
        "fractions that leave no test part are refused",
    )


CHECKS: dict[str, Callable[[ModuleType], None]] = {
    "wind_vector": check_wind_vector,
    "nea_hour_to_utc": check_nea_hour_to_utc,
    "chronological_split": check_chronological_split,
}
