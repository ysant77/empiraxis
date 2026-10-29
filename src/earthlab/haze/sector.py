"""H1 core: lagged wind and rain sector check for one onset hour and one source box.

For each lag L, the hours [onset - L, onset) are read from the corridor-mean wind and
rain series. The check is "consistent" when at least half the non-calm hours blow from
the source sector, the wind moved air at least half the source distance toward the
receptor, no hour had path rain above the washout limit, and data are complete enough.
This is geometry and timing only. It gives no concentration and no attribution.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from earthlab.contracts import Strict
from earthlab.haze.evidence import SourceRef
from earthlab.haze.geometry import SourceBox
from earthlab.haze.timebase import to_utc
from earthlab.haze.wind import CALM_SPEED_MS, angular_difference, blows_from_source, wind_from_uv

MS_HOUR_TO_KM = 3.6


class TransportStatus(StrEnum):
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    INCONCLUSIVE = "inconclusive"


class H1Params(Strict):
    lags_hours: tuple[int, ...] = (12, 24, 36, 48, 72)
    tolerance_deg: float = Field(default=45.0, gt=0, le=90)
    min_in_sector_fraction: float = Field(default=0.5, gt=0, le=1)
    min_advection_fraction: float = Field(default=0.5, gt=0)
    rain_limit_mm_h: float = Field(default=1.0, gt=0)
    max_missing_fraction: float = Field(default=0.1, ge=0, lt=1)
    calm_ms: float = Field(default=CALM_SPEED_MS, ge=0)
    fire_min_confidence: int = Field(default=30, ge=0, le=100)


class MetHour(Strict):
    """Corridor-mean values for one UTC hour. Precipitation: mm in the hour ending here."""

    time: datetime
    u_ms: float | None
    v_ms: float | None
    precip_mm: float | None

    @field_validator("time")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return to_utc(value)


class MetSeries(Strict):
    box_id: str
    level: Literal["10m", "850hPa"]
    hours: tuple[MetHour, ...]
    sources: tuple[SourceRef, ...] = Field(min_length=1)

    def lookup(self) -> dict[datetime, MetHour]:
        return {hour.time: hour for hour in self.hours}


class LagCheck(Strict):
    lag_hours: int
    hours_checked: int
    missing_hours: int
    calm_hours: int
    in_sector_fraction: float | None
    advected_km: float
    max_precip_mm_h: float | None
    rain_affected: bool
    status: TransportStatus


def _window(onset_utc: datetime, lag_hours: int) -> list[datetime]:
    return [onset_utc - timedelta(hours=h) for h in range(lag_hours, 0, -1)]


def _status(
    params: H1Params, missing: int, total: int, rain: bool, fraction: float | None, ratio: float
) -> TransportStatus:
    if missing > params.max_missing_fraction * total or rain or fraction is None:
        return TransportStatus.INCONCLUSIVE
    if fraction >= params.min_in_sector_fraction and ratio >= params.min_advection_fraction:
        return TransportStatus.CONSISTENT
    return TransportStatus.INCONSISTENT


def lag_check(
    series: dict[datetime, MetHour],
    source: SourceBox,
    onset_utc: datetime,
    lag_hours: int,
    params: H1Params,
) -> LagCheck:
    bearing, missing, calm, in_sector, advected = source.bearing_deg, 0, 0, 0, 0.0
    precip: list[float] = []
    for moment in _window(onset_utc, lag_hours):
        hour = series.get(moment)
        if hour is None or hour.u_ms is None or hour.v_ms is None:
            missing += 1
            continue
        if hour.precip_mm is not None:
            precip.append(hour.precip_mm)
        reading = wind_from_uv(hour.u_ms, hour.v_ms, params.calm_ms)
        if reading.from_deg is None:
            calm += 1
            continue
        in_sector += blows_from_source(reading, bearing, params.tolerance_deg)
        toward = math.cos(math.radians(angular_difference(reading.from_deg, bearing)))
        advected += reading.speed_ms * toward * MS_HOUR_TO_KM
    moving = lag_hours - missing - calm
    fraction = in_sector / moving if moving else None
    max_precip = max(precip, default=None)
    rain = max_precip is not None and max_precip > params.rain_limit_mm_h
    ratio = advected / source.distance_km
    return LagCheck(
        lag_hours=lag_hours,
        hours_checked=lag_hours,
        missing_hours=missing,
        calm_hours=calm,
        in_sector_fraction=fraction,
        advected_km=round(advected, 3),
        max_precip_mm_h=max_precip,
        rain_affected=rain,
        status=_status(params, missing, lag_hours, rain, fraction, ratio),
    )


def combine(checks: list[LagCheck]) -> TransportStatus:
    """Consistent at any lag wins; otherwise any inconclusive lag makes the box inconclusive."""
    statuses = {check.status for check in checks}
    if TransportStatus.CONSISTENT in statuses:
        return TransportStatus.CONSISTENT
    if TransportStatus.INCONCLUSIVE in statuses:
        return TransportStatus.INCONCLUSIVE
    return TransportStatus.INCONSISTENT
