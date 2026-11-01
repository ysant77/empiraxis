"""The NEA file as an hourly grid, with its audit. No value is repaired or filled.

This reader does not use the investigation loader, because the audit must see the rows that
loader resolves. A label with conflicting rows is excluded as a target and as an input
(section 7.1 of docs/science-data-forecast-protocol.md).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from earthlab.digest import file_digest

REGIONS = ("north", "south", "east", "west", "central")
GRID_START = datetime(2014, 4, 1, 1)
GRID_END = datetime(2026, 10, 1, 0)  # inclusive, the last published label
EXCLUDED_LABELS = (
    datetime(2016, 3, 7, 0),
    datetime(2016, 3, 7, 12),
    datetime(2016, 4, 4, 0),
    datetime(2016, 4, 4, 10),
    datetime(2018, 4, 24, 0),
    datetime(2018, 4, 25, 0),
    datetime(2018, 8, 16, 2),
    datetime(2018, 8, 16, 3),
)
SPLITS = {
    "train": (datetime(2014, 4, 1, 1), datetime(2018, 12, 31, 23)),
    "validation": (datetime(2019, 1, 1, 0), datetime(2023, 12, 31, 23)),
    "test": (datetime(2024, 1, 1, 0), datetime(2026, 10, 1, 0)),
}


@dataclass(frozen=True)
class Audit:
    source_sha256: str
    rows: int
    grid_hours: int
    first_label: str
    last_label: str
    unparsed_labels: tuple[str, ...]
    duplicate_labels: int
    conflicting_labels: tuple[str, ...]
    absent_labels: int
    excluded_labels: int
    missing_by_region: dict[str, int]
    non_numeric_cells: int
    negative_cells: int
    rows_by_year: dict[str, int]
    missing_by_year: dict[str, int]
    longest_gap_hours: int


@dataclass(frozen=True)
class Grid:
    """Hourly values, shape (hours, regions). NaN means no usable published value."""

    values: np.ndarray
    source_sha256: str

    @property
    def hours(self) -> int:
        return int(self.values.shape[0])


def parse_label(text: str) -> datetime | None:
    """A printed label as naive SGT. A malformed label returns None and is never guessed."""
    try:
        day, clock = text.strip().split()
        d, m, y = (int(p) for p in day.split("/"))
        hour, minute = clock.split(":")
        if len(hour) > 2:
            return None
        return datetime(y, m, d, int(hour), int(minute))
    except ValueError:
        return None


def index_of(label: datetime) -> int:
    return int((label - GRID_START).total_seconds() // 3600)


def label_at(index: int) -> datetime:
    return GRID_START + timedelta(hours=index)


def _cells(row: list[str]) -> tuple[list[float], int, int]:
    out, bad, negative = [], 0, 0
    for cell in row:
        try:
            value = float(cell)
        except ValueError:
            bad += 1
            out.append(float("nan"))
            continue
        if value < 0:
            negative += 1
            out.append(float("nan"))
        else:
            out.append(value)
    return out, bad, negative


def _read(path: Path) -> tuple[dict[datetime, list[list[float]]], list[str], int, int, int]:
    rows: dict[datetime, list[list[float]]] = {}
    unparsed: list[str] = []
    count = bad = negative = 0
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        next(reader)
        for row in reader:
            count += 1
            label = parse_label(row[0])
            if label is None or not GRID_START <= label <= GRID_END:
                unparsed.append(row[0])
                continue
            values, b, n = _cells(row[1:6])
            bad, negative = bad + b, negative + n
            rows.setdefault(label, []).append(values)
    return rows, unparsed, count, bad, negative


def _longest_gap(missing: np.ndarray) -> int:
    longest = run = 0
    for gap in missing:
        run = run + 1 if gap else 0
        longest = max(longest, run)
    return longest


def load_grid(path: Path) -> tuple[Grid, Audit]:
    rows, unparsed, count, bad, negative = _read(path)
    hours = index_of(GRID_END) + 1
    grid = np.full((hours, len(REGIONS)), np.nan)
    duplicates, conflicts = 0, []
    for label, found in rows.items():
        if len(found) > 1:
            duplicates += 1
            if any(not np.array_equal(found[0], other, equal_nan=True) for other in found[1:]):
                conflicts.append(label)
        grid[index_of(label)] = found[0]
    excluded = sorted(set(EXCLUDED_LABELS) | set(conflicts))
    for label in excluded:
        grid[index_of(label)] = np.nan
    absent = hours - len(rows)
    missing = np.isnan(grid)
    years = [label_at(i).year for i in range(hours)]
    year_array = np.array(years)
    by_year = {str(y): int(missing[year_array == y].sum()) for y in sorted(set(years))}
    rows_year: dict[str, int] = {}
    for label in rows:
        rows_year[str(label.year)] = rows_year.get(str(label.year), 0) + 1
    source = file_digest(path)
    audit = Audit(
        source_sha256=source,
        rows=count,
        grid_hours=hours,
        first_label=min(rows).isoformat(),
        last_label=max(rows).isoformat(),
        unparsed_labels=tuple(unparsed),
        duplicate_labels=duplicates,
        conflicting_labels=tuple(c.isoformat() for c in sorted(conflicts)),
        absent_labels=absent,
        excluded_labels=len(excluded),
        missing_by_region={r: int(missing[:, i].sum()) for i, r in enumerate(REGIONS)},
        non_numeric_cells=bad,
        negative_cells=negative,
        rows_by_year=rows_year,
        missing_by_year=by_year,
        longest_gap_hours=_longest_gap(missing.all(axis=1)),
    )
    return Grid(grid, source), audit
