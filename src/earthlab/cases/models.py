"""Typed records for one scientific case: where, when, which data, what was found, and
what a human approved.

Every record forbids unknown fields and cannot change after creation. Each validator fails
closed: an unknown time zone, an unbounded area, an unpinned "pinned" asset or a causal
verdict the system cannot support is an error, not a default.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from earthlab.contracts import Region, Strict, TimeWindow

MAX_AREA_SPAN_DEG = 5.0
SHA256 = r"^[0-9a-f]{64}$"
IDENT = r"^[a-z0-9][a-z0-9._/-]*$"
CLAIM_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"  # finding IDs such as R1.2


class ScientificVariable(StrEnum):
    BURNED_AREA = "burned_area"
    ACTIVE_FIRE = "active_fire"
    VEGETATION_CHANGE = "vegetation_change"
    AIR_TEMPERATURE_ANOMALY = "air_temperature_anomaly"
    LAND_SURFACE_TEMPERATURE = "land_surface_temperature"
    WIND_CONSISTENCY = "wind_consistency"
    AIR_POLLUTION_OBSERVATION = "air_pollution_observation"


class BoundingBox(Strict):
    """Longitude/latitude box in EPSG:4326. Boxes across the antimeridian are refused."""

    min_lon: float = Field(ge=-180, le=180)
    min_lat: float = Field(ge=-90, le=90)
    max_lon: float = Field(ge=-180, le=180)
    max_lat: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.min_lon >= self.max_lon:
            raise ValueError("min_lon must be below max_lon; antimeridian boxes are not supported")
        if self.min_lat >= self.max_lat:
            raise ValueError("min_lat must be below max_lat")
        return self

    def contains(self, other: BoundingBox) -> bool:
        return (
            self.min_lon <= other.min_lon
            and self.min_lat <= other.min_lat
            and self.max_lon >= other.max_lon
            and self.max_lat >= other.max_lat
        )


class StudyArea(Strict):
    """Exactly one geometry: a bounded box, or named NEA regions (areas, not points)."""

    area_id: str = Field(pattern=IDENT)
    name: str = Field(min_length=1)
    crs: Literal["EPSG:4326"] = "EPSG:4326"
    bbox: BoundingBox | None = None
    regions: tuple[Region, ...] = ()
    geojson_ref: str | None = None
    geojson_sha256: str | None = Field(default=None, pattern=SHA256)

    @model_validator(mode="after")
    def _one_geometry(self) -> Self:
        if (self.bbox is None) == (not self.regions):
            raise ValueError("give exactly one of bbox or regions")
        if self.geojson_ref is not None and self.geojson_sha256 is None:
            raise ValueError("a GeoJSON reference needs its sha256")
        box = self.bbox
        if box and max(box.max_lon - box.min_lon, box.max_lat - box.min_lat) > MAX_AREA_SPAN_DEG:
            raise ValueError(f"study area wider than {MAX_AREA_SPAN_DEG} degrees")
        return self


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("missing time zone; give an offset or Z")
    return value.astimezone(UTC)


class StudyPeriod(Strict):
    """Half-open interval [start, end) stored in UTC, with the local zone for labels."""

    start: datetime
    end: datetime
    local_zone: str

    @field_validator("start", "end")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @field_validator("local_zone")
    @classmethod
    def _zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {value!r}") from exc
        return value

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("period end must be after period start")
        return self

    @property
    def days(self) -> float:
        return (self.end - self.start) / timedelta(days=1)

    def contains(self, other: StudyPeriod) -> bool:
        return self.start <= other.start and other.end <= self.end

    def local_label(self) -> str:
        zone = ZoneInfo(self.local_zone)
        start, end = self.start.astimezone(zone), self.end.astimezone(zone)
        return f"{start.isoformat()} to {end.isoformat()} (end excluded, {self.local_zone})"

    def to_window(self) -> TimeWindow:
        """The NEA tool window (Singapore time, at most 92 days) for the same instants."""
        return TimeWindow(start=self.start, end=self.end)


Availability = Literal["pinned", "registered_not_downloaded", "unavailable"]


class SourceAsset(Strict):
    """One data source as this project holds it. 'unavailable' means access, coverage or
    licence is not yet verified for this case, not that the product does not exist."""

    asset_id: str = Field(pattern=IDENT)
    product: str = Field(min_length=1)
    version: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    variable: ScientificVariable
    units: str = Field(min_length=1)
    licence: str = Field(min_length=1)
    licence_url: str
    url: str
    availability: Availability
    sha256: str | None = Field(default=None, pattern=SHA256)
    bytes: int | None = Field(default=None, gt=0)
    retrieved_at_utc: datetime | None = None
    crs: str = Field(min_length=1)
    resolution_m: float | None = Field(default=None, gt=0)
    coverage: StudyPeriod
    extent: BoundingBox | None = None
    regions: tuple[Region, ...] = ()
    quality_policy: str | None = None
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _pin_matches_availability(self) -> Self:
        pinned = (self.sha256, self.bytes, self.retrieved_at_utc)
        if self.availability == "pinned" and None in pinned:
            raise ValueError("a pinned asset needs sha256, bytes and retrieved_at_utc")
        if self.availability != "pinned" and any(v is not None for v in pinned):
            raise ValueError("only a pinned asset may carry sha256, bytes or retrieval time")
        if self.retrieved_at_utc is not None:
            _aware_utc(self.retrieved_at_utc)
        return self

    def covers(self, area: StudyArea) -> bool:
        if area.bbox is not None:
            return self.extent is not None and self.extent.contains(area.bbox)
        return set(area.regions) <= set(self.regions)


class ObservationStatus(StrEnum):
    SUPPORTED_OBSERVATION = "supported_observation"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_VERIFIED = "not_verified"


class CausalStatus(StrEnum):
    """No 'established' value exists: no validated attribution protocol is in scope."""

    NOT_REQUESTED = "not_requested"
    NOT_ESTABLISHED = "not_established"
    INSUFFICIENT_DATA = "insufficient_data"


class EvidenceClaim(Strict):
    """One computed finding. Observation support and causal status are kept apart."""

    claim_id: str = Field(pattern=CLAIM_ID)
    case_id: str = Field(pattern=IDENT)
    method_id: str = Field(pattern=IDENT)
    variable: ScientificVariable
    area: StudyArea
    period: StudyPeriod
    value: float | None = None
    unit: str = Field(min_length=1)
    source_sha256: tuple[str, ...] = ()
    valid_fraction: float | None = Field(default=None, ge=0, le=1)
    observation_status: ObservationStatus
    causal_status: CausalStatus = CausalStatus.NOT_REQUESTED

    @field_validator("source_sha256")
    @classmethod
    def _hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(len(h) != 64 or set(h) - set("0123456789abcdef") for h in value):
            raise ValueError("source_sha256 entries must be lowercase SHA-256 hex")
        return value

    @model_validator(mode="after")
    def _supported_has_evidence(self) -> Self:
        if self.observation_status is ObservationStatus.SUPPORTED_OBSERVATION and (
            self.value is None or not self.source_sha256 or self.valid_fraction is None
        ):
            raise ValueError("a supported observation needs value, source_sha256, valid_fraction")
        return self


class ApprovalAction(StrEnum):
    CONFIRM_STUDY_AREA = "confirm_study_area"
    DOWNLOAD = "download"
    HOSTED_MODEL_SPEND = "hosted_model_spend"
    SANDBOX_EXECUTION = "sandbox_execution"
    PUBLISH = "publish"


class HumanApproval(Strict):
    """A human decision about one consequential action. No model tool can create one."""

    approval_id: str = Field(pattern=IDENT)
    case_id: str = Field(pattern=IDENT)
    action: ApprovalAction
    approved: bool
    approver: str = Field(min_length=1)
    decided_at_utc: datetime
    expires_at_utc: datetime
    asset_ids: tuple[str, ...] = ()
    max_bytes: int | None = Field(default=None, gt=0)
    max_usd: float | None = Field(default=None, gt=0)

    @field_validator("decided_at_utc", "expires_at_utc")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _scoped(self) -> Self:
        if self.expires_at_utc <= self.decided_at_utc:
            raise ValueError("an approval must expire after it is decided")
        if self.action is ApprovalAction.HOSTED_MODEL_SPEND and self.max_usd is None:
            raise ValueError("a spend approval needs max_usd")
        if self.action is ApprovalAction.DOWNLOAD and (not self.asset_ids or not self.max_bytes):
            raise ValueError("a download approval needs asset_ids and max_bytes")
        return self

    def refusal(
        self,
        action: ApprovalAction,
        at: datetime,
        *,
        asset_id: str | None = None,
        request_bytes: int | None = None,
        request_usd: float | None = None,
    ) -> str | None:
        """Why this approval does not cover the request, or None when it does.

        A download must name its asset and size, and a spend its amount; each must fit
        inside the approved scope.
        """
        if not self.approved:
            return "the approval was rejected"
        if action is not self.action:
            return f"approval covers {self.action.value}, not {action.value}"
        if not self.decided_at_utc <= _aware_utc(at) < self.expires_at_utc:
            return "the approval is not valid at this time"
        return self._scope_refusal(asset_id, request_bytes, request_usd)

    def _scope_refusal(
        self, asset_id: str | None, request_bytes: int | None, request_usd: float | None
    ) -> str | None:
        if self.action is ApprovalAction.DOWNLOAD:
            if asset_id is None or asset_id not in self.asset_ids:
                return f"asset {asset_id} is not in the approval"
            if request_bytes is None or self.max_bytes is None or request_bytes > self.max_bytes:
                return f"download of {request_bytes} bytes exceeds or lacks the approved cap"
        if self.action is ApprovalAction.HOSTED_MODEL_SPEND and (
            request_usd is None or self.max_usd is None or request_usd > self.max_usd
        ):
            return f"spend of {request_usd} USD exceeds or lacks the approved cap"
        return None


class ScientificCase(Strict):
    """A bounded research question bound to one area, one period and named assets."""

    case_id: str = Field(pattern=IDENT)
    title: str = Field(min_length=1)
    question: str = Field(min_length=5)
    area: StudyArea
    period: StudyPeriod
    variable: ScientificVariable
    asset_ids: tuple[str, ...] = Field(min_length=1)
    method_id: str = Field(pattern=IDENT)
    causal_claim_requested: bool = False
    status: Literal["active", "draft"] = "draft"
    data_dir: str | None = Field(default=None, description="Pinned data folder, repo-relative.")
    notes: str | None = None

    def default_causal_status(self) -> CausalStatus:
        if self.causal_claim_requested:
            return CausalStatus.NOT_ESTABLISHED
        return CausalStatus.NOT_REQUESTED
