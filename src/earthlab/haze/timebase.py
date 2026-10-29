"""Map NEA hour labels (Singapore local time) to UTC intervals for joining with ERA5.

NEA does not state whether a label marks the start or the end of its hour, so the
convention is an explicit argument. Singapore has no daylight saving time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from earthlab.contracts import SGT

ONE_HOUR = timedelta(hours=1)


class HourConvention(StrEnum):
    HOUR_ENDING = "hour_ending"
    HOUR_BEGINNING = "hour_beginning"


def to_utc(value: datetime) -> datetime:
    """Convert an aware time to UTC. A naive time is refused, never guessed."""
    if value.tzinfo is None:
        raise ValueError("time must carry a time zone; naive times are refused")
    return value.astimezone(UTC)


def nea_label_to_utc_interval(
    label: datetime, convention: HourConvention
) -> tuple[datetime, datetime]:
    """The half-open UTC hour [start, end) that an NEA label covers under a convention.

    A naive label is read as Singapore time, as the NEA file prints it.
    """
    local = label.replace(tzinfo=SGT) if label.tzinfo is None else label.astimezone(SGT)
    if local.minute or local.second or local.microsecond:
        raise ValueError(f"NEA labels are on the hour, got {local.isoformat()}")
    end = local if convention is HourConvention.HOUR_ENDING else local + ONE_HOUR
    return to_utc(end - ONE_HOUR), to_utc(end)
