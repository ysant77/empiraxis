"""Parse the NEA Historical 1-hr PM2.5 CSV into a sorted, de-duplicated hourly series.

The parser never fills gaps and never drops a problem silently: every repair is recorded
as a ``ParseIssue`` that the quality report and the agent can see.
"""

from __future__ import annotations

import csv
import re
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from earthlab.contracts import ALL_REGIONS, SGT, Region, SourceSnapshot, TimeWindow

TIME_COLUMN = "1hr_pm25"
_DMY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4}) (\d{1,2}):(\d{2})$")
# One real row reads "2016-04-04 010:00:00": ISO date with a zero-padded three-digit hour.
_ISO_PADDED = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) 0*(\d{1,2}):(\d{2}):(\d{2})$")


class IssueKind(StrEnum):
    ALTERNATE_TIME_FORMAT = "alternate_time_format"
    UNPARSEABLE_TIME = "unparseable_time"
    DUPLICATE_HOUR = "duplicate_hour"
    CONFLICTING_DUPLICATE = "conflicting_duplicate"
    NON_NUMERIC = "non_numeric"
    NEGATIVE_VALUE = "negative_value"
    OUT_OF_ORDER = "out_of_order"


@dataclass(frozen=True, slots=True)
class ParseIssue:
    kind: IssueKind
    line: int
    detail: str


@dataclass(frozen=True, slots=True)
class HourRow:
    time: datetime
    values: dict[Region, float | None]


@dataclass(frozen=True)
class Pm25Dataset:
    snapshot: SourceSnapshot
    rows: tuple[HourRow, ...]
    issues: tuple[ParseIssue, ...]
    _index: dict[datetime, HourRow] = field(repr=False, compare=False)

    def at(self, moment: datetime) -> HourRow | None:
        return self._index.get(moment)

    def in_window(self, window: TimeWindow) -> list[HourRow]:
        lo = bisect_left(self.rows, window.start, key=lambda r: r.time)
        hi = bisect_left(self.rows, window.end, key=lambda r: r.time)
        return list(self.rows[lo:hi])

    def issue_counts(self) -> dict[str, int]:
        return dict(Counter(issue.kind.value for issue in self.issues))


def parse_time(raw: str) -> tuple[datetime, bool]:
    """Return the Singapore time of a label and whether it used the alternate format."""
    text = raw.strip()
    if match := _DMY.match(text):
        day, month, year, hour, minute = (int(g) for g in match.groups())
        return datetime(year, month, day, hour, minute, tzinfo=SGT), False
    if match := _ISO_PADDED.match(text):
        year, month, day, hour, minute, _ = (int(g) for g in match.groups())
        return datetime(year, month, day, hour, minute, tzinfo=SGT), True
    raise ValueError(f"unrecognised time label {text!r}")


def _parse_value(raw: str, line: int, region: Region, issues: list[ParseIssue]) -> float | None:
    text = raw.strip()
    try:
        value = float(text)
    except ValueError:
        issues.append(ParseIssue(IssueKind.NON_NUMERIC, line, f"{region}={text!r}"))
        return None
    if value < 0:
        issues.append(ParseIssue(IssueKind.NEGATIVE_VALUE, line, f"{region}={value}"))
        return None
    return value


def _check_header(header: list[str] | None) -> None:
    expected = [TIME_COLUMN, *[r.value for r in ALL_REGIONS]]
    if [h.strip().lower() for h in header or []] != expected:
        raise ValueError(f"unexpected NEA header {header}; expected {expected}")


def _read_rows(path: Path, issues: list[ParseIssue]) -> list[tuple[int, HourRow]]:
    parsed: list[tuple[int, HourRow]] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        _check_header(next(reader, None))
        for line, record in enumerate(reader, start=2):
            try:
                moment, alternate = parse_time(record[0])
            except (ValueError, IndexError):
                issues.append(ParseIssue(IssueKind.UNPARSEABLE_TIME, line, repr(record[:1])))
                continue
            if alternate:
                issues.append(ParseIssue(IssueKind.ALTERNATE_TIME_FORMAT, line, record[0]))
            cells = (record[1:] + [""] * len(ALL_REGIONS))[: len(ALL_REGIONS)]
            values = {
                region: _parse_value(raw, line, region, issues)
                for region, raw in zip(ALL_REGIONS, cells, strict=True)
            }
            parsed.append((line, HourRow(moment, values)))
    return parsed


def _deduplicate(parsed: list[tuple[int, HourRow]], issues: list[ParseIssue]) -> list[HourRow]:
    """Keep the first row for each hour; record every duplicate and any conflict."""
    kept: dict[datetime, HourRow] = {}
    previous: datetime | None = None
    for line, row in parsed:
        if previous is not None and row.time < previous:
            issues.append(ParseIssue(IssueKind.OUT_OF_ORDER, line, row.time.isoformat()))
        previous = row.time
        first = kept.get(row.time)
        if first is None:
            kept[row.time] = row
            continue
        kind = IssueKind.DUPLICATE_HOUR
        if first.values != row.values:
            kind = IssueKind.CONFLICTING_DUPLICATE
        issues.append(ParseIssue(kind, line, row.time.isoformat()))
    return sorted(kept.values(), key=lambda r: r.time)


def load_pm25(path: Path, snapshot: SourceSnapshot) -> Pm25Dataset:
    """Parse a hash-verified NEA file. Call ``open_snapshot`` first to verify the hash."""
    issues: list[ParseIssue] = []
    rows = _deduplicate(_read_rows(path, issues), issues)
    return Pm25Dataset(
        snapshot=snapshot,
        rows=tuple(rows),
        issues=tuple(issues),
        _index={row.time: row for row in rows},
    )
