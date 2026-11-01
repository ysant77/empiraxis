"""What a data product is, what time it is known, and whether it can join a task.

`DatasetSuitabilityV1` is a profile that code builds from a manifest or from a catalogue
entry. A model never writes it. `preflight` joins the profiles of a task and fails closed:
if a fact is absent, the join is refused. ERA5 is a reanalysis. It supports a hindsight
diagnostic and never an operational forecast input.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from earthlab.cases.models import BoundingBox
from earthlab.contracts import Strict

Availability = Literal["logged", "modelled", "unknown", "not_applicable"]
DataKind = Literal["observation", "reanalysis", "issued_forecast", "derived_product", "weights"]
LocalState = Literal["verified", "hash_mismatch", "unverified", "absent", "not_acquired"]
Permission = Literal[
    "covered_signed", "recorded_active", "recorded_expired", "chat_only_unsigned",
    "needs_approval", "denied", "not_required",
]  # fmt: skip
Evidence = Literal[
    "historical_research", "hindsight_diagnostic", "issue_time_forecast",
    "transport_plausibility", "method_input",
]  # fmt: skip
Arm = Literal["issue_time_forecast", "hindsight_diagnostic", "retrospective_association"]
TimeConvention = Literal["instant", "hour_ending", "hour_beginning", "interval", "unknown"]
Support = Literal["point", "region", "grid_cell", "swath", "scene"]
Accumulation = Literal["instant", "accumulated", "rate", "not_applicable"]


class VariableSpec(Strict):
    name: str = Field(max_length=60)
    unit: str = Field(max_length=30)
    accumulation: Accumulation = "not_applicable"


class DatasetSuitabilityV1(Strict):
    schema_version: Literal["1"] = "1"
    dataset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")
    revision: str = Field(max_length=80)
    source_url: str = Field(max_length=500)
    variables: tuple[VariableSpec, ...] = Field(min_length=1)
    crs: str | None = None
    grid: str | None = None
    area: BoundingBox | None = None
    first_time: datetime | None = None
    last_time: datetime | None = None
    cadence_hours: float | None = Field(default=None, gt=0)
    spatial_support: Support
    event_time: TimeConvention
    valid_time: TimeConvention
    data_kind: DataKind
    availability: Availability
    available_at_field: str | None = None
    latency_hours: float | None = Field(default=None, ge=0)
    optical: bool = False
    quality_masks: tuple[str, ...] = ()
    missing_fraction: float | None = Field(default=None, ge=0, le=1)
    license: str = Field(max_length=200)
    bytes_estimate: int | None = Field(default=None, ge=0)
    local_state: LocalState
    local_path: str | None = None
    local_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    allowed_evidence: tuple[Evidence, ...] = ()
    permission: Permission
    permission_expires_utc: datetime | None = None
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> DatasetSuitabilityV1:
        for stamp in (self.first_time, self.last_time):
            if stamp is not None and stamp.tzinfo is None:
                raise ValueError("a profile time must carry a time zone")
        if self.local_state == "verified" and self.local_sha256 is None:
            raise ValueError("a verified file needs its sha256")
        if self.availability == "logged" and self.available_at_field is None:
            raise ValueError("logged availability needs the name of the available-at field")
        if self.availability == "modelled" and self.latency_hours is None:
            raise ValueError("modelled availability needs a latency")
        reanalysis = self.data_kind == "reanalysis"
        if reanalysis and "issue_time_forecast" in self.allowed_evidence:
            raise ValueError("a reanalysis is never an issue-time forecast input")
        return self


class Code(StrEnum):
    MALFORMED_TIMESTAMP = "malformed_timestamp"
    NAIVE_TIMESTAMP = "naive_timestamp"
    DUPLICATE_TIMESTAMP = "duplicate_timestamp"
    NOT_VERIFIED = "not_verified"
    NOT_ACQUIRED = "not_acquired"
    MISSING_AVAILABLE_AT = "missing_available_at"
    REANALYSIS_AS_FORECAST = "reanalysis_as_forecast"
    MODELLED_AVAILABILITY = "modelled_availability"
    HINDSIGHT_LABEL = "hindsight_label"
    MISSING_VARIABLE = "missing_variable"
    UNIT_MISMATCH = "unit_mismatch"
    OUT_OF_AOI = "out_of_aoi"
    AOI_PARTIAL = "aoi_partial"
    AOI_UNKNOWN = "aoi_unknown"
    OUT_OF_TIME = "out_of_time"
    TIME_PARTIAL = "time_partial"
    NO_OBSERVATION = "no_observation"
    MISSINGNESS_UNKNOWN = "missingness_unknown"
    CLOUD_MASK_MISSING = "cloud_mask_missing"
    MISALIGNED_CADENCE = "misaligned_cadence"
    MISALIGNED_SUPPORT = "misaligned_support"
    TIME_CONVENTION_UNKNOWN = "time_convention_unknown"
    LEAKAGE = "leakage"


class Finding(Strict):
    dataset_id: str
    code: Code
    blocking: bool
    detail: str


class JoinPlanV1(Strict):
    """What one task needs from its inputs. It may end as not alignable."""

    schema_version: Literal["1"] = "1"
    target_id: str
    arm: Arm
    inputs: tuple[str, ...] = Field(min_length=1)
    aoi: BoundingBox
    window_start: datetime
    window_end: datetime
    expected_units: dict[str, str]
    target_cadence_hours: float = Field(gt=0)
    target_support: Support
    spatial_aggregation: str | None = None
    lag_hours: int = Field(default=0, ge=0)
    max_missing_fraction: float = Field(default=0.2, ge=0, le=1)
    evaluation_start: datetime | None = None


class AlignmentReportV1(Strict):
    schema_version: Literal["1"] = "1"
    target_id: str
    arm: Arm
    verdict: Literal["aligned", "aligned_with_caveats", "not_alignable"]
    findings: tuple[Finding, ...]


class TimestampError(ValueError):
    """The text is not an ISO 8601 time with a zone."""


def parse_timestamp(text: str) -> datetime:
    """Strict ISO 8601 with a zone. A naive or malformed text is refused, never guessed."""
    try:
        moment = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise TimestampError(f"not an ISO 8601 time: {text!r}") from None
    if moment.tzinfo is None:
        raise TimestampError(f"no time zone: {text!r}")
    return moment.astimezone(UTC)


def check_timestamps(dataset_id: str, texts: list[str]) -> list[Finding]:
    """Findings for malformed, naive and repeated stamps of one raw series."""
    out: list[Finding] = []
    seen: set[datetime] = set()
    for text in texts:
        try:
            moment = parse_timestamp(text)
        except TimestampError as exc:
            naive = "no time zone" in str(exc)
            code = Code.NAIVE_TIMESTAMP if naive else Code.MALFORMED_TIMESTAMP
            out.append(Finding(dataset_id=dataset_id, code=code, blocking=True, detail=str(exc)))
            continue
        if moment in seen:
            detail = f"repeated stamp {moment.isoformat()}"
            out.append(Finding(dataset_id=dataset_id, code=Code.DUPLICATE_TIMESTAMP,
                               blocking=True, detail=detail))  # fmt: skip
        seen.add(moment)
    return out


def _find(profile: DatasetSuitabilityV1, code: Code, blocking: bool, detail: str) -> Finding:
    return Finding(dataset_id=profile.dataset_id, code=code, blocking=blocking, detail=detail)


def _inside(inner: BoundingBox, outer: BoundingBox) -> bool:
    return (
        outer.min_lon <= inner.min_lon and inner.max_lon <= outer.max_lon
        and outer.min_lat <= inner.min_lat and inner.max_lat <= outer.max_lat
    )  # fmt: skip


def _disjoint(a: BoundingBox, b: BoundingBox) -> bool:
    return (
        a.max_lon < b.min_lon or b.max_lon < a.min_lon
        or a.max_lat < b.min_lat or b.max_lat < a.min_lat
    )  # fmt: skip


def _availability(plan: JoinPlanV1, p: DatasetSuitabilityV1) -> list[Finding]:
    if plan.arm == "hindsight_diagnostic" and p.data_kind == "reanalysis":
        return [
            _find(p, Code.HINDSIGHT_LABEL, False, "label the result a perfect-weather hindcast")
        ]
    if plan.arm != "issue_time_forecast":
        return []
    out = []
    if p.data_kind == "reanalysis":
        out.append(_find(p, Code.REANALYSIS_AS_FORECAST, True, "reanalysis was not known at issue"))
    if p.availability in ("unknown", "not_applicable"):
        out.append(_find(p, Code.MISSING_AVAILABLE_AT, True, "no available-at metadata"))
    if p.availability == "modelled":
        out.append(_find(p, Code.MODELLED_AVAILABILITY, False, "label it a modelled hindcast"))
    return out


def _units(plan: JoinPlanV1, p: DatasetSuitabilityV1) -> list[Finding]:
    have = {v.name: v for v in p.variables}
    out = []
    for name, unit in plan.expected_units.items():
        if name not in have:
            continue
        if have[name].unit != unit:
            detail = f"{name} is {have[name].unit}, the task needs {unit}"
            out.append(_find(p, Code.UNIT_MISMATCH, True, detail))
    return out


def _space_time(plan: JoinPlanV1, p: DatasetSuitabilityV1) -> list[Finding]:
    out = []
    if p.area is None:
        out.append(_find(p, Code.AOI_UNKNOWN, True, "the area of the data is not stated"))
    elif _disjoint(plan.aoi, p.area):
        out.append(_find(p, Code.OUT_OF_AOI, True, "the data lie outside the task area"))
    elif not _inside(plan.aoi, p.area):
        out.append(_find(p, Code.AOI_PARTIAL, True, "the data cover only part of the task area"))
    if p.first_time is None or p.last_time is None:
        return out
    if p.last_time <= plan.window_start or p.first_time >= plan.window_end:
        out.append(_find(p, Code.OUT_OF_TIME, True, "the data lie outside the task window"))
    elif p.first_time > plan.window_start or p.last_time < plan.window_end:
        out.append(_find(p, Code.TIME_PARTIAL, True, "the data cover only part of the window"))
    return out


def _quality(plan: JoinPlanV1, p: DatasetSuitabilityV1) -> list[Finding]:
    out = []
    if p.missing_fraction is None:
        out.append(_find(p, Code.MISSINGNESS_UNKNOWN, False, "the missing fraction is unknown"))
    elif p.missing_fraction > plan.max_missing_fraction:
        detail = f"missing fraction {p.missing_fraction:.2f} above {plan.max_missing_fraction:.2f}"
        out.append(_find(p, Code.NO_OBSERVATION, True, detail))
    if p.optical and "cloud" not in p.quality_masks:
        out.append(_find(p, Code.CLOUD_MASK_MISSING, True, "optical data with no cloud mask"))
    return out


def _supports(plan: JoinPlanV1, p: DatasetSuitabilityV1) -> list[Finding]:
    out = []
    step = p.cadence_hours
    if step is not None and (step > plan.target_cadence_hours
                             or plan.target_cadence_hours % step):  # fmt: skip
        detail = f"cadence {step} h does not divide the {plan.target_cadence_hours} h target"
        out.append(_find(p, Code.MISALIGNED_CADENCE, True, detail))
    if p.spatial_support != plan.target_support:
        text = f"{p.spatial_support} data against a {plan.target_support} target"
        out.append(_find(p, Code.MISALIGNED_SUPPORT, plan.spatial_aggregation is None, text))
    if p.valid_time == "unknown":
        out.append(_find(p, Code.TIME_CONVENTION_UNKNOWN, False, "run a convention sensitivity"))
    return out


def _state(p: DatasetSuitabilityV1) -> list[Finding]:
    if p.local_state == "not_acquired":
        return [_find(p, Code.NOT_ACQUIRED, True, "the product is not on this machine")]
    if p.local_state != "verified":
        return [_find(p, Code.NOT_VERIFIED, True, f"local state is {p.local_state}")]
    return []


def _leak(target: str, detail: str) -> Finding:
    return Finding(dataset_id=target, code=Code.LEAKAGE, blocking=True, detail=detail)


def preflight(plan: JoinPlanV1, profiles: list[DatasetSuitabilityV1]) -> AlignmentReportV1:
    """Join checks over every input. Any blocking finding makes the plan not alignable."""
    by_id = {p.dataset_id: p for p in profiles}
    findings: list[Finding] = []
    for name in plan.inputs:
        profile = by_id.get(name)
        if profile is None:
            findings.append(Finding(dataset_id=name, code=Code.NOT_ACQUIRED, blocking=True,
                                    detail="no profile for this input"))  # fmt: skip
            continue
        findings += _state(profile)
        for check in (_availability, _units, _space_time, _quality, _supports):
            findings += check(plan, profile)
    if plan.evaluation_start is not None and plan.window_end > plan.evaluation_start:
        detail = "the input window reaches into the evaluation period"
        findings.append(_leak(plan.target_id, detail))
    blocked = any(f.blocking for f in findings)
    verdict = "not_alignable" if blocked else "aligned_with_caveats" if findings else "aligned"
    return AlignmentReportV1(
        target_id=plan.target_id, arm=plan.arm, verdict=verdict, findings=tuple(findings)
    )
