from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from earthlab.contracts import SGT, Region, TimeWindow
from earthlab.data.nea_pm25 import Pm25Dataset
from earthlab.data.quality import coverage_report


def test_window_rules() -> None:
    with pytest.raises(ValidationError):
        TimeWindow(start=datetime(2015, 9, 2), end=datetime(2015, 9, 1))
    with pytest.raises(ValidationError):
        TimeWindow(start=datetime(2015, 1, 1), end=datetime(2015, 6, 1))
    window = TimeWindow(start=datetime(2015, 9, 1, 0, 30), end=datetime(2015, 9, 1, 3))
    assert [h.hour for h in window.hours()] == [1, 2]
    assert window.start.tzinfo is SGT or window.start.utcoffset() == SGT.utcoffset(None)
    assert "end excluded" in window.label()


def test_coverage_counts_missing_cells_and_absent_hours(small_dataset: Pm25Dataset) -> None:
    window = TimeWindow(start=datetime(2015, 9, 1, 0), end=datetime(2015, 9, 1, 6))
    report = coverage_report(small_dataset, window)
    assert report.missing_for(Region.NORTH) == 2  # hours 4 and 5 absent
    east = next(c for c in report.regions if c.region == Region.EAST)
    assert east.missing_hours == 3
    assert [(g.start.hour, g.hours) for g in east.gaps] == [(1, 1), (4, 2)]


def test_real_2015_haze_window_is_complete(real_dataset: Pm25Dataset) -> None:
    window = TimeWindow(start=datetime(2015, 9, 1), end=datetime(2015, 11, 1))
    report = coverage_report(real_dataset, window)
    assert all(c.missing_hours == 0 for c in report.regions)
    assert all(c.expected_hours == 1464 for c in report.regions)
