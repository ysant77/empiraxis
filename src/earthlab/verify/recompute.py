"""An independent reader of the raw NEA file, used only by the verifier.

It shares no parsing code with ``earthlab.data``: it re-reads the bytes, re-checks the
hash and rebuilds the hourly values with its own simple rules. If the two code paths
disagree, the verifier reports a contradiction instead of trusting the agent's tools.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from earthlab.contracts import ALL_REGIONS, Region, TimeWindow

Key = tuple[datetime, Region]


class SourceHashError(RuntimeError):
    """The verifier refuses a file whose hash differs from the pinned one."""


def _label_to_naive(label: str) -> datetime:
    day_part, time_part = label.strip().split(" ")
    hour = int(time_part.split(":")[0])
    if "/" in day_part:
        day, month, year = (int(x) for x in day_part.split("/"))
    else:
        year, month, day = (int(x) for x in day_part.split("-"))
    return datetime(year, month, day) + timedelta(hours=hour)


def _cell(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value >= 0 else None


class IndependentSource:
    def __init__(self, values: dict[Key, float]):
        self._values = values

    @classmethod
    def from_file(cls, path: Path, expected_sha256: str) -> IndependentSource:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise SourceHashError(f"{path.name} does not match the pinned hash")
        values: dict[Key, float] = {}
        seen: set[datetime] = set()
        for line in raw.decode("utf-8-sig").splitlines()[1:]:
            cells = line.split(",")
            try:
                moment = _label_to_naive(cells[0])
            except (ValueError, IndexError):
                continue
            if moment in seen:
                continue  # first occurrence wins, as published order
            seen.add(moment)
            for region, text in zip(ALL_REGIONS, cells[1:], strict=False):
                value = _cell(text)
                if value is not None:
                    values[(moment, region)] = value
        return cls(values)

    def series(
        self, region: Region, window: TimeWindow
    ) -> tuple[list[tuple[datetime, float]], int]:
        """Observed (hour, value) pairs in local naive time, and the expected hour count."""
        hours = [h.replace(tzinfo=None) for h in window.hours()]
        pairs = [(h, self._values[(h, region)]) for h in hours if (h, region) in self._values]
        return pairs, len(hours)
