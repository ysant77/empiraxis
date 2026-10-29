"""Where, when, what quantity, which data and which methods a plan considers.

Area and period reuse `StudyArea` and `StudyPeriod` from the case models, so a plan and a
case share one validated geometry and one half-open UTC interval. A data candidate reuses
the case footprint types but names its own quantity, because a plan may consider data that
no case can hold yet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from earthlab.cases.models import (
    IDENT,
    SHA256,
    Availability,
    BoundingBox,
    StudyArea,
    StudyPeriod,
)
from earthlab.contracts import Region, Strict
from earthlab.planning.vocab import (
    Compute,
    DataRole,
    MethodClass,
    ProductKind,
    Quantity,
    Technique,
)

SpatialSupport = Literal["named_region", "station", "pixel", "grid_cell", "area_total"]


class Aoi(Strict):
    """The study area, its spatial support, and where its boundary came from."""

    area: StudyArea
    spatial_support: SpatialSupport
    boundary_source: str = Field(min_length=1)
    boundary_version: str = Field(min_length=1)


class TimeRange(Strict):
    """Observation period as [start, end) in UTC, plus a forecast issue time if any.

    `forecast_issue_time` is the instant a prediction is made. Every input must be known
    at that instant. Data publication delay lives on each data candidate.
    """

    period: StudyPeriod
    convention: Literal["half_open_utc"] = "half_open_utc"
    forecast_issue_time: datetime | None = None

    @field_validator("forecast_issue_time")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("forecast_issue_time needs a time zone")
        return value


class Target(Strict):
    quantity: Quantity
    unit: str = Field(min_length=1)
    temporal_resolution: Literal["hour", "day", "month", "period_total"]
    spatial_support: SpatialSupport
    spatial_resolution_m: float | None = Field(default=None, gt=0)


class PeriodFraction(Strict):
    """Valid fraction measured for one sub-period, for example one product month."""

    period: StudyPeriod
    valid_fraction: float = Field(ge=0, le=1)


class DataCandidate(Strict):
    """One dataset the plan considers. Footprint fields reuse the case types."""

    dataset_id: str = Field(pattern=IDENT)
    product: str = Field(min_length=1)
    version: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    licence: str = Field(min_length=1)
    availability: Availability
    sha256: str | None = Field(default=None, pattern=SHA256)
    quantity: Quantity
    units: str = Field(min_length=1)
    product_kind: ProductKind
    native_variables: tuple[str, ...] = Field(min_length=1)
    crs: str = Field(min_length=1)
    resolution_m: float | None = Field(default=None, gt=0)
    coverage: StudyPeriod
    extent: BoundingBox | None = None
    regions: tuple[Region, ...] = ()
    availability_latency_hours: float = Field(ge=0)
    valid_fraction: float | None = Field(default=None, ge=0, le=1)
    valid_fraction_by_period: tuple[PeriodFraction, ...] = ()
    missing_data_policy: str = Field(min_length=1)
    quality_policy: str | None = None
    bands: tuple[str, ...] = ()
    normalization: str | None = None
    quality_mask: str | None = None

    @model_validator(mode="after")
    def _pinned_has_hash(self) -> Self:
        if (self.availability == "pinned") != (self.sha256 is not None):
            raise ValueError("a pinned dataset needs sha256, and only a pinned one has it")
        return self

    def valid_fraction_for(self, period: StudyPeriod) -> float | None:
        """Lowest measured fraction over sub-periods that overlap `period`.

        With no sub-periods, the single total. With sub-periods but none that overlap,
        None: no measurement exists for that period.
        """
        if not self.valid_fraction_by_period:
            return self.valid_fraction
        parts = [
            p.valid_fraction
            for p in self.valid_fraction_by_period
            if p.period.start < period.end and period.start < p.period.end
        ]
        return min(parts) if parts else None

    def covers(self, area: StudyArea) -> bool:
        if area.bbox is not None:
            return self.extent is not None and self.extent.contains(area.bbox)
        return set(area.regions) <= set(self.regions)


class DataUse(Strict):
    """How a method uses one dataset: as which quantity and as which product kind.

    The critic compares these claims with the dataset's own `quantity` and `product_kind`.
    """

    dataset_id: str = Field(pattern=IDENT)
    used_as: Quantity
    assumed_kind: ProductKind
    role: DataRole = "input"


class ImageRequirements(Strict):
    """What an image model needs from its input scenes."""

    bands: tuple[str, ...] = Field(min_length=1)
    normalization: str = Field(min_length=1)
    needs_quality_mask: bool = True


class PlanMethod(Strict):
    """A method the plan considers. `catalogue_id` links an implemented catalogue entry."""

    method_id: str = Field(pattern=IDENT)
    catalogue_id: str | None = Field(default=None, pattern=IDENT)
    method_class: MethodClass
    technique: Technique
    inputs: tuple[DataUse, ...] = Field(min_length=1)
    feasibility: Literal["feasible", "needs_approval", "not_implemented", "blocked"]
    assumptions: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    runtime_estimate_s: float = Field(gt=0)
    compute: Compute = "laptop_cpu"
    min_valid_fraction: float = Field(default=0.75, ge=0, le=1)
    image_requirements: ImageRequirements | None = None

    @model_validator(mode="after")
    def _segmentation_states_needs(self) -> Self:
        if self.technique == "image_segmentation" and self.image_requirements is None:
            raise ValueError("image segmentation needs image_requirements")
        return self

    def input_ids(self, role: DataRole = "input") -> tuple[str, ...]:
        return tuple(u.dataset_id for u in self.inputs if u.role == role)


class RejectedMethod(Strict):
    method_id: str = Field(pattern=IDENT)
    reason: str = Field(min_length=1)


class MethodChoice(Strict):
    selected_id: str = Field(pattern=IDENT)
    rationale: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    simpler_baseline_id: str | None = Field(default=None, pattern=IDENT)
    rejected: tuple[RejectedMethod, ...] = ()
