"""Shared, strict data contracts: regions, time windows and source snapshots.

Every model forbids unknown fields, so a malformed or injected payload fails loudly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SGT = timezone(timedelta(hours=8), name="Asia/Singapore")
MAX_WINDOW_DAYS = 92
PM25_UNIT = "ug/m3"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Region(StrEnum):
    """The five NEA reporting regions. These are areas, not station coordinates."""

    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    CENTRAL = "central"


ALL_REGIONS: tuple[Region, ...] = tuple(Region)


def to_sgt(value: datetime) -> datetime:
    """Read a naive time as Singapore local time; convert an aware time to it."""
    if value.tzinfo is None:
        return value.replace(tzinfo=SGT)
    return value.astimezone(SGT)


class TimeWindow(Strict):
    """Half-open interval [start, end) in Singapore local time, at most 92 days long."""

    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _localise(cls, value: datetime) -> datetime:
        return to_sgt(value)

    @model_validator(mode="after")
    def _check_span(self) -> Self:
        if self.end <= self.start:
            raise ValueError("window end must be after window start")
        if self.end - self.start > timedelta(days=MAX_WINDOW_DAYS):
            raise ValueError(f"window longer than {MAX_WINDOW_DAYS} days")
        return self

    def hours(self) -> list[datetime]:
        """Every whole hour label inside the window, in order."""
        moment = self.start.replace(minute=0, second=0, microsecond=0)
        if moment < self.start:
            moment += timedelta(hours=1)
        labels: list[datetime] = []
        while moment < self.end:
            labels.append(moment)
            moment += timedelta(hours=1)
        return labels

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def label(self) -> str:
        return f"{self.start.isoformat()} to {self.end.isoformat()} (end excluded)"


class SourceSnapshot(Strict):
    """Pinned provenance of one source file. The hash is checked before every use."""

    dataset_id: str
    title: str
    publisher: str
    source_url: str
    licence: str
    licence_url: str
    attribution: str
    file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0)
    retrieved_at_utc: datetime
    timezone: str
    time_label_convention: str
    unit: str
    measure: str
    spatial_support: str

    def citation(self) -> dict[str, str]:
        """The fields every tool result and report must carry."""
        return {
            "dataset_id": self.dataset_id,
            "source_url": self.source_url,
            "sha256": self.sha256,
            "licence": self.licence,
            "unit": self.unit,
            "timezone": self.timezone,
            "spatial_support": self.spatial_support,
        }
