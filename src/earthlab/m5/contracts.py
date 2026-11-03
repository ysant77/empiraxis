"""Typed, versioned contracts for M5 science data: products, receipts, QA and transforms.

Every model forbids unknown fields. A receipt without a SHA-256, a time without a zone, or an
availability rule that claims an earlier time than the observation fails at construction.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from earthlab.cases.models import BoundingBox
from earthlab.contracts import Strict

CONTRACT_VERSION = "m5-contracts-1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _require_utc(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() != UTC.utcoffset(None)):
        raise ValueError("time must be timezone-aware UTC")
    return value


class TimeKind(StrEnum):
    INSTANTANEOUS = "instantaneous"
    INTERVAL_MEAN = "interval_mean"
    INTERVAL_ACCUMULATION = "interval_accumulation"
    OVERPASS = "overpass"
    MONTHLY = "monthly"


class DataRole(StrEnum):
    OBSERVATION = "observation"
    REANALYSIS = "reanalysis"
    ESTIMATE = "estimate"  # satellite precipitation estimate, retrieval
    ISSUED_FORECAST = "issued_forecast"


class ProductPin(Strict):
    """One exact product and revision. A run flavour (Early, Late, Final) is part of the pin."""

    dataset_id: str = Field(min_length=1)
    product: str = Field(min_length=1)
    version: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    licence: str = Field(min_length=1)
    licence_url: str = Field(min_length=1)
    run: str | None = None
    role: DataRole


class TimeSupport(Strict):
    """What a stamp means. `stamp_marks` says where in the interval the label sits."""

    kind: TimeKind
    step_hours: float | None = Field(default=None, gt=0)
    stamp_marks: Literal["start", "end", "instant", "unknown"] = "unknown"
    accumulation_hours: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _accumulation(self) -> Self:
        if self.kind is TimeKind.INTERVAL_ACCUMULATION and self.accumulation_hours is None:
            raise ValueError("an accumulation needs accumulation_hours")
        return self


class Availability(Strict):
    """When a value could be read. `available_at` is null when unknown; then a bound is needed."""

    observation_end_utc: datetime
    available_at_utc: datetime | None = None
    assumed_latency_hours: float | None = Field(default=None, ge=0)
    basis: Literal["recorded", "nominal_latency", "hindsight_only"]

    _utc = field_validator("observation_end_utc", "available_at_utc")(_require_utc)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.available_at_utc and self.available_at_utc < self.observation_end_utc:
            raise ValueError("available_at cannot be before the observation ends")
        if self.basis == "recorded" and self.available_at_utc is None:
            raise ValueError("basis 'recorded' needs available_at_utc")
        if self.basis == "nominal_latency" and self.assumed_latency_hours is None:
            raise ValueError("basis 'nominal_latency' needs assumed_latency_hours")
        return self

    def usable_at(self, issue_utc: datetime) -> bool:
        """True only when the value is provably or by a stated bound visible at issue time."""
        _require_utc(issue_utc)
        if self.basis == "hindsight_only":
            return False
        if self.basis == "recorded" and self.available_at_utc is not None:
            return self.available_at_utc <= issue_utc
        assert self.assumed_latency_hours is not None
        return self.observation_end_utc + timedelta(hours=self.assumed_latency_hours) <= issue_utc


class QAMaskSpec(Strict):
    """A QA rule. Rejected cells stay missing; they are never replaced by a number."""

    name: str
    field: str
    rule: str
    action: Literal["reject", "flag"] = "reject"
    reason: str


class GridSpec(Strict):
    crs: str
    footprint: BoundingBox
    resolution_m: float | None = Field(default=None, gt=0)
    resolution_deg: float | None = Field(default=None, gt=0)


class AcquisitionReceipt(Strict):
    """Immutable record of one retrieved file. Raw bytes stay outside Git."""

    schema_version: str = CONTRACT_VERSION
    receipt_id: str
    product: ProductPin
    source_uri: str
    local_path: str
    sha256: str
    bytes: int = Field(gt=0)
    retrieved_at_utc: datetime
    authority: str = Field(min_length=1)
    byte_cap: int = Field(gt=0)
    grid: GridSpec | None = None
    time_support: TimeSupport | None = None
    observation_start_utc: datetime | None = None
    observation_end_utc: datetime | None = None
    units: str | None = None
    missing_value: str | None = None
    qa_masks: tuple[QAMaskSpec, ...] = ()

    _utc = field_validator("retrieved_at_utc", "observation_start_utc", "observation_end_utc")(
        _require_utc
    )

    @field_validator("sha256")
    @classmethod
    def _digest(cls, value: str) -> str:
        if not SHA256.match(value):
            raise ValueError("sha256 must be 64 lowercase hex digits")
        return value

    @model_validator(mode="after")
    def _cap(self) -> Self:
        if self.bytes > self.byte_cap:
            raise ValueError("file is larger than its byte cap")
        return self


class FeatureTransform(Strict):
    """A derived feature, its code version and the digests of the sources it read."""

    feature_id: str
    transform_version: str
    formula: str
    unit: str
    source_sha256: tuple[str, ...] = Field(min_length=1)
    data_class: Literal["issue_time_valid", "hindsight"]

    @field_validator("source_sha256")
    @classmethod
    def _digests(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not all(SHA256.match(v) for v in values):
            raise ValueError("every source digest must be 64 lowercase hex digits")
        return values
