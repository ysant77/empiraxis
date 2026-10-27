from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from conftest import DatasetFactory

from earthlab.contracts import SGT, Region, TimeWindow
from earthlab.data.nea_pm25 import IssueKind, Pm25Dataset, load_pm25, parse_time
from earthlab.data.snapshot import SourceMismatchError, open_snapshot


def test_parse_time_accepts_both_published_formats() -> None:
    assert parse_time("1/9/2015 7:00") == (datetime(2015, 9, 1, 7, tzinfo=SGT), False)
    assert parse_time("2016-04-04 010:00:00") == (datetime(2016, 4, 4, 10, tzinfo=SGT), True)
    with pytest.raises(ValueError):
        parse_time("Sept 1 2015")


def test_small_file_is_sorted_deduplicated_and_issues_recorded(small_dataset: Pm25Dataset) -> None:
    times = [row.time.hour for row in small_dataset.rows]
    assert times == [0, 1, 2, 3]
    counts = small_dataset.issue_counts()
    assert counts[IssueKind.DUPLICATE_HOUR] == 1
    assert counts[IssueKind.NON_NUMERIC] == 1
    assert counts[IssueKind.ALTERNATE_TIME_FORMAT] == 1
    assert counts[IssueKind.OUT_OF_ORDER] == 1
    row = small_dataset.at(datetime(2015, 9, 1, 1, tzinfo=SGT))
    assert row is not None and row.values[Region.EAST] is None


def test_conflicting_duplicates_negative_and_bad_time_are_reported(
    make_data_dir: DatasetFactory,
) -> None:
    data_dir = make_data_dir(
        [
            "1/9/2015 0:00,10,20,30,40,50",
            "1/9/2015 0:00,11,20,30,40,50",
            "1/9/2015 1:00,-3,20,30,40",
            "not a time,1,2,3,4,5",
        ]
    )
    snapshot, path = open_snapshot(data_dir)
    dataset = load_pm25(path, snapshot)
    counts = dataset.issue_counts()
    assert counts[IssueKind.CONFLICTING_DUPLICATE] == 1
    assert counts[IssueKind.NEGATIVE_VALUE] == 1
    assert counts[IssueKind.NON_NUMERIC] == 1  # the short row's missing central cell
    assert counts[IssueKind.UNPARSEABLE_TIME] == 1


def test_wrong_header_is_rejected(make_data_dir: DatasetFactory) -> None:
    snapshot, csv_path = open_snapshot(make_data_dir([]))
    csv_path.write_text("time,a,b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        load_pm25(csv_path, snapshot)


def test_modified_file_fails_closed(make_data_dir: DatasetFactory) -> None:
    data_dir = make_data_dir(["1/9/2015 0:00,10,20,30,40,50"])
    with (data_dir / "pm25.csv").open("a", encoding="utf-8") as fh:
        fh.write("1/9/2015 1:00,99,99,99,99,99\n")
    with pytest.raises(SourceMismatchError, match="does not match"):
        open_snapshot(data_dir)


def test_missing_file_fails_closed(make_data_dir: DatasetFactory) -> None:
    data_dir = make_data_dir([])
    Path(data_dir / "pm25.csv").unlink()
    with pytest.raises(SourceMismatchError, match="missing"):
        open_snapshot(data_dir)


def test_real_snapshot_shape(real_dataset: Pm25Dataset) -> None:
    window = TimeWindow(start=datetime(2015, 9, 1), end=datetime(2015, 11, 1))
    assert len(real_dataset.in_window(window)) == 61 * 24
    counts = real_dataset.issue_counts()
    assert counts[IssueKind.ALTERNATE_TIME_FORMAT] == 1
    assert (
        counts.get(IssueKind.DUPLICATE_HOUR, 0) + counts.get(IssueKind.CONFLICTING_DUPLICATE, 0)
        == 4
    )
