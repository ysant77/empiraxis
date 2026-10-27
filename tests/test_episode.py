from __future__ import annotations

from datetime import date, datetime

from earthlab.contracts import SGT, Region, TimeWindow
from earthlab.data.nea_pm25 import Pm25Dataset
from earthlab.science.episode import Statistic, daily_peaks, hours_above, rank_regions, summarize

HAZE = TimeWindow(start=datetime(2015, 9, 1), end=datetime(2015, 11, 1))


def test_summary_ignores_missing_cells(small_dataset: Pm25Dataset) -> None:
    window = TimeWindow(start=datetime(2015, 9, 1), end=datetime(2015, 9, 1, 4))
    east = summarize(small_dataset, window, Region.EAST)
    assert (east.observed_hours, east.missing_hours) == (3, 1)
    assert east.mean == round((30 + 31 + 34) / 3, 1)
    assert east.max == 34 and east.max_at == datetime(2015, 9, 1, 3, tzinfo=SGT)


def test_empty_window_has_no_statistics(small_dataset: Pm25Dataset) -> None:
    window = TimeWindow(start=datetime(2016, 1, 1), end=datetime(2016, 1, 2))
    summary = summarize(small_dataset, window, Region.NORTH)
    assert summary.mean is None and summary.max is None and summary.missing_hours == 24
    ranked = rank_regions(small_dataset, window, Statistic.MEAN)
    assert all(r.value is None for r in ranked)


def test_ranking_daily_peaks_and_threshold(small_dataset: Pm25Dataset) -> None:
    window = TimeWindow(start=datetime(2015, 9, 1), end=datetime(2015, 9, 3))
    ranked = rank_regions(small_dataset, window, Statistic.MAX)
    assert ranked[0].region == Region.WEST and ranked[0].value == 400
    peaks = daily_peaks(small_dataset, window, Region.WEST)
    assert [(p.day, p.max, p.observed_hours) for p in peaks] == [
        (date(2015, 9, 1), 400, 4),
        (date(2015, 9, 2), None, 0),
    ]
    assert hours_above(small_dataset, window, Region.WEST, 41) == 2


def test_real_haze_peak_is_west_on_19_october(real_dataset: Pm25Dataset) -> None:
    ranked = rank_regions(real_dataset, HAZE, Statistic.MAX)
    assert ranked[0].region == Region.WEST and ranked[0].value == 471
    west = summarize(real_dataset, HAZE, Region.WEST)
    assert west.max_at == datetime(2015, 10, 19, 23, tzinfo=SGT)
