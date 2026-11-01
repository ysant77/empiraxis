"""Strict contracts for haze dataset descriptors and as-of-safe prediction features.

A descriptor holds what the Engineering Lab shows for one candidate dataset: what it
measures, where and when, how it was made, its licence, size and acquisition state.
A feature set refuses any input that was not available at the prediction issue time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from earthlab.cases.models import BoundingBox
from earthlab.contracts import Strict


class EvidenceClass(StrEnum):
    """Claim strength, weakest first. CAUSAL_INFERENCE exists so it can be refused."""

    OBSERVATION = "observation"
    ASSOCIATION = "association"
    TRANSPORT_PLAUSIBILITY = "transport_plausibility"
    HINDCAST = "hindcast"
    FORECAST = "forecast"
    CAUSAL_INFERENCE = "causal_inference"


class TimeRole(StrEnum):
    """How a value relates to time: measured, re-analysed after the fact, or forecast."""

    OBSERVATION = "observation"
    REANALYSIS = "reanalysis"
    FORECAST = "forecast"


class TemporalKind(StrEnum):
    INSTANTANEOUS = "instantaneous"
    OVERPASS = "overpass"
    HOURLY_MEAN = "hourly_mean"
    HOURLY_ACCUMULATION = "hourly_accumulation"
    MONTHLY_MAP = "monthly_map"


class SpatialKind(StrEnum):
    REPORTING_REGION = "reporting_region"
    GRID_CELL = "grid_cell"
    DETECTION_PIXEL = "detection_pixel"
    RASTER_PIXEL = "raster_pixel"


class Permission(StrEnum):
    """Acquisition state. Every state except PINNED needs an owner decision first."""

    PINNED = "pinned"
    OWNER_APPROVAL = "owner_approval"
    OWNER_APPROVAL_AND_ACCOUNT = "owner_approval_and_account"
    DEFERRED = "deferred"
    REFERENCE_ONLY = "reference_only"


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("time must carry a time zone; naive times are refused")
    return value.astimezone(UTC)


class TemporalSupport(Strict):
    kind: TemporalKind
    step_hours: float | None = Field(default=None, gt=0)
    note: str = ""


class SpatialSupport(Strict):
    kind: SpatialKind
    resolution_m: float | None = Field(default=None, gt=0)
    note: str = ""


class QaFlag(Strict):
    name: str = Field(min_length=1)
    meaning: str = Field(min_length=1)


class DatasetDescriptor(Strict):
    """One candidate haze dataset, as the Engineering Lab renders it."""

    dataset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    product: str = Field(min_length=1)
    variable: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    aoi: BoundingBox
    valid_start: datetime
    valid_end: datetime
    issue_time: datetime | None = None
    time_role: TimeRole
    temporal_support: TemporalSupport
    spatial_support: SpatialSupport
    missingness: str = Field(min_length=1)
    qa_flags: tuple[QaFlag, ...] = ()
    licence: str = Field(min_length=1)
    licence_url: str = Field(pattern=r"^https://")
    size_estimate_bytes: int = Field(ge=0)
    size_is_estimate: bool
    permission: Permission
    max_evidence_class: EvidenceClass
    method_suitability: str = Field(min_length=1)
    not_for: tuple[str, ...] = ()
    synthetic: bool = False

    @field_validator("valid_start", "valid_end", "issue_time")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.valid_end <= self.valid_start:
            raise ValueError("valid_end must be after valid_start")
        if self.time_role is TimeRole.FORECAST and self.issue_time is None:
            raise ValueError("a forecast dataset needs an issue_time")
        if self.time_role is not TimeRole.FORECAST and self.issue_time is not None:
            raise ValueError("only a forecast dataset has an issue_time")
        if self.max_evidence_class is EvidenceClass.CAUSAL_INFERENCE:
            raise ValueError("no single dataset supports causal inference")
        if self.max_evidence_class is EvidenceClass.FORECAST and self.time_role is not (
            TimeRole.FORECAST
        ):
            raise ValueError("only archived forecast runs can support the forecast class")
        return self


class PredictorFeature(Strict):
    """One input value to a prediction, with the times that decide if it may be used."""

    name: str = Field(min_length=1)
    time_role: TimeRole
    valid_time: datetime
    source_issue_time: datetime | None = None
    available_at: datetime | None = None

    @field_validator("valid_time", "source_issue_time", "available_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)

    @model_validator(mode="after")
    def _issue_for_forecast(self) -> Self:
        if self.time_role is TimeRole.FORECAST and self.source_issue_time is None:
            raise ValueError(f"forecast feature {self.name!r} needs its source issue time")
        return self

    def known_by(self) -> datetime:
        """The earliest time this value could have been known."""
        if self.available_at is not None:
            return self.available_at
        if self.time_role is TimeRole.FORECAST:
            assert self.source_issue_time is not None
            return self.source_issue_time
        return self.valid_time


class FeatureSet(Strict):
    """Inputs for one prediction issued at issue_time. Any look-ahead is refused.

    An observation or reanalysis value is known no earlier than its valid time, so a
    valid time after the issue time is a leak. A reanalysis is published long after its
    valid time, so it needs a recorded publication time. A forecast value may be valid
    later, but its run must have been issued, and published, by the issue time.
    """

    issue_time: datetime
    target_valid_time: datetime
    features: tuple[PredictorFeature, ...]

    @field_validator("issue_time", "target_valid_time")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def _no_look_ahead(self) -> Self:
        if self.target_valid_time <= self.issue_time:
            raise ValueError("target must be valid after the issue time")
        for feature in self.features:
            if feature.time_role is TimeRole.REANALYSIS and feature.available_at is None:
                raise ValueError(
                    f"feature {feature.name!r} is not known at issue time: "
                    "a reanalysis value needs its publication time"
                )
            if feature.known_by() > self.issue_time:
                raise ValueError(
                    f"feature {feature.name!r} ({feature.time_role.value}) was not known "
                    f"at issue time {self.issue_time.isoformat()}"
                )
        return self
