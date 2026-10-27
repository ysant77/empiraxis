"""Typed claims the agent may submit, and the verdicts the verifier returns.

A claim is a narrow, checkable statement about observed values. Free text is allowed
only as a short statement that must agree with the typed fields.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from earthlab.contracts import Region, Strict, TimeWindow

MAX_STATEMENT_CHARS = 300


class ClaimKind(StrEnum):
    REGION_MAX = "region_max"
    REGION_MEAN = "region_mean"
    PEAK_REGION = "peak_region"
    MISSING_HOURS = "missing_hours"
    HOURS_ABOVE = "hours_above"


_NEEDS_VALUE = {
    ClaimKind.REGION_MAX,
    ClaimKind.REGION_MEAN,
    ClaimKind.MISSING_HOURS,
    ClaimKind.HOURS_ABOVE,
}


class Claim(Strict):
    kind: ClaimKind = Field(
        description=(
            "region_max: highest hourly value in a region; region_mean: mean (1 decimal); "
            "peak_region: region with the highest hourly value; missing_hours: count of "
            "missing hours in a region; hours_above: hours strictly above threshold."
        )
    )
    region: Region = Field(
        description="The region the claim is about (for peak_region: the winner)."
    )
    start: datetime = Field(description="Window start, Singapore local time, ISO 8601.")
    end: datetime = Field(description="Window end (excluded), Singapore local time, ISO 8601.")
    value: float | None = Field(default=None, description="Claimed number in ug/m3 or hours.")
    threshold: float | None = Field(default=None, ge=0, description="Only for hours_above.")
    at: datetime | None = Field(default=None, description="Optional hour of the max (region_max).")
    statement: str = Field(max_length=MAX_STATEMENT_CHARS, description="One plain sentence.")

    @model_validator(mode="after")
    def _fields_match_kind(self) -> Self:
        TimeWindow(start=self.start, end=self.end)
        if self.kind in _NEEDS_VALUE and self.value is None:
            raise ValueError(f"{self.kind} needs a value")
        if (self.kind is ClaimKind.HOURS_ABOVE) != (self.threshold is not None):
            raise ValueError("threshold is required for hours_above and only for it")
        if self.at is not None and self.kind is not ClaimKind.REGION_MAX:
            raise ValueError("'at' is only allowed for region_max")
        return self

    @property
    def window(self) -> TimeWindow:
        return TimeWindow(start=self.start, end=self.end)


class Verdict(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNSUPPORTED = "unsupported"
    INSUFFICIENT_DATA = "insufficient_data"


class Check(StrEnum):
    """Bounded names for what failed or passed; safe as metric labels."""

    VALUE = "value"
    LANGUAGE = "language"
    COVERAGE = "coverage"
    SOURCE = "source"


class VerificationResult(Strict):
    claim: Claim
    verdict: Verdict
    check: Check
    observed: float | str | None = None
    reason: str
