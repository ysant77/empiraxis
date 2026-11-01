"""The synthetic toy series for the pilot. All values come from a seeded generator.

The numbers carry no physical meaning and describe no real place or period. A series is
an AR(1) process: phi below one reverts to the level, and phi equal to one is a random walk.
"""

from __future__ import annotations

import random
from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.method.contracts import DataClassification, canonical_digest

SYNTHETIC_ID = r"^synthetic-[a-z0-9-]{1,60}$"


class ToySeriesV1(Strict):
    """One evenly labelled synthetic series. The classification admits no real data."""

    schema_version: Literal["1"] = "1"
    dataset_id: str = Field(pattern=SYNTHETIC_ID)
    classification: DataClassification = "synthetic_development"
    steps: tuple[int, ...]
    values: tuple[float, ...]


def synthetic_series(
    dataset_id: str, *, seed: int, phi: float, length: int, level: float = 40.0, sigma: float = 1.0
) -> ToySeriesV1:
    """Generate y[t] = level + phi * (y[t-1] - level) + noise, rounded to four decimals."""
    rng = random.Random(seed)  # noqa: S311 - reproducible noise, not security
    values = [level]
    for _ in range(length - 1):
        values.append(level + phi * (values[-1] - level) + rng.gauss(0.0, sigma))
    return ToySeriesV1(
        dataset_id=dataset_id,
        steps=tuple(range(length)),
        values=tuple(round(v, 4) for v in values),
    )


def series_digest(series: ToySeriesV1) -> str:
    return canonical_digest(series)
