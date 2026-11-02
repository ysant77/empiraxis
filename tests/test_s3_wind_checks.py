"""S3 wind, rain and clock checks, and the fixed verdict rule. Synthetic inputs only."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from haze_synthetic import SYNTHETIC_REF, episode, met_series, steady, write_nea

from earthlab.contracts import SGT
from earthlab.harness import s3_wind
from earthlab.haze.sector import MetHour, MetSeries
from earthlab.haze.transport_checks import (
    accumulate_mm,
    check_clock,
    check_precip,
    rate_mm_h,
    sign_tests,
    speed_ms,
    towards_bearing,
    wind_sign_error,
)
from earthlab.haze.wind import wind_from_uv


def test_every_sign_case_gives_the_wind_from_bearing() -> None:
    results = sign_tests()
    assert len(results) == 5 and all(r.passed for r in results)
    westerly = wind_from_uv(5.0, 0.0)
    assert westerly.from_deg == 270.0 and speed_ms(3.0, 4.0) == 5.0


def test_a_towards_bearing_given_as_wind_from_is_a_sign_error() -> None:
    assert towards_bearing(5.0, 0.0) == 90.0
    assert wind_sign_error(5.0, 0.0, claimed_from_deg=90.0)
    assert not wind_sign_error(5.0, 0.0, claimed_from_deg=270.0)
    assert not wind_sign_error(0.1, 0.1, claimed_from_deg=45.0)  # calm: no direction


def test_a_rain_total_is_not_a_rate_until_divided_by_its_interval() -> None:
    hourly = [1.0, 2.0, 0.0, 3.0]
    assert accumulate_mm(hourly, 2) == [3.0, 2.0, 3.0]
    assert rate_mm_h(6.0, 3.0) == 2.0
    with pytest.raises(ValueError, match="positive"):
        rate_mm_h(1.0, 0.0)
    with pytest.raises(ValueError, match="one hour"):
        accumulate_mm(hourly, 0)


def test_a_running_total_is_not_taken_for_hourly_rain() -> None:
    running = [float(i) for i in range(1, 25)]
    check = check_precip(running)
    assert check.looks_cumulative and check.longest_rising_run == 23
    showers = [0.0, 0.2, 0.5, 0.9, 1.1, 1.4, 1.8, 2.2, 2.5, 3.0, 3.1, 3.3, 3.5, 3.8, 4.0, 4.4]
    assert not check_precip(showers).looks_cumulative  # a long rain onset is short of a day
    assert not check_precip([0.0] * 40).looks_cumulative  # a dry spell is not a total
    hourly = check_precip([0.0, 1.2, 0.3, 0.0, 2.0, None, 0.1])
    assert not hourly.looks_cumulative and hourly.missing == 1 and not hourly.issues


def test_a_unit_slip_between_metres_and_millimetres_is_caught() -> None:
    assert check_precip([0.002, 0.004], unit="m").max_mm_h == pytest.approx(4.0)
    slipped = check_precip([150.0, 3.0], unit="m")
    assert slipped.implausible_rate and "unit" in slipped.issues[0]
    assert check_precip([-0.5]).negative == 1


def _series(times: list[datetime]) -> MetSeries:
    hours = tuple(MetHour(time=t, u_ms=1.0, v_ms=1.0, precip_mm=0.0) for t in times)
    return MetSeries(box_id="box-a", level="10m", hours=hours, sources=(SYNTHETIC_REF,))


def test_the_clock_must_be_regular_hourly_utc() -> None:
    start = datetime(2015, 9, 1, tzinfo=UTC)
    good = check_clock(_series([start + timedelta(hours=i) for i in range(5)]))
    assert good.passed
    gap = check_clock(_series([start, start + timedelta(hours=3)]))
    again = check_clock(_series([start, start]))
    odd = check_clock(_series([start, start + timedelta(minutes=30)]))
    assert (gap.gaps, again.repeats, odd.off_hour) == (1, 1, 1)
    assert not (gap.passed or again.passed or odd.passed)


def test_the_verdict_rule_is_fixed() -> None:
    decide = s3_wind.decide
    assert decide(0.8, 0.2, 30, 40) == "consistent"
    assert decide(0.8, 0.7, 30, 40) == "inconclusive"  # clean hours pass too: no specificity
    assert decide(0.1, 0.1, 30, 40) == "inconsistent"
    assert decide(0.4, 0.1, 30, 40) == "inconclusive"
    assert decide(0.9, 0.1, 5, 40) == "inconclusive"  # too few onsets
    assert decide(None, 0.1, 30, 40) == "inconclusive"


def test_run_s3_never_attributes_a_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s3_wind, "TOLERANCES", (45.0,))
    monkeypatch.setattr(s3_wind, "RAIN_LIMITS", (1.0,))
    monkeypatch.setattr(s3_wind, "LAG_SETS", ((12, 24),))
    monkeypatch.setattr(s3_wind, "MIN_EVENT_DECIDED", 1)
    monkeypatch.setattr(s3_wind, "MIN_CLEAN_DECIDED", 1)
    nea = write_nea(tmp_path / "nea", episode(datetime(2015, 9, 20, 6, tzinfo=SGT), 8, 120.0))
    series = met_series(steady(8.0))
    extract = tmp_path / "extract.json"
    payload = {"series": [s.model_dump(mode="json") for s in series.values()]}
    extract.write_text(json.dumps(payload), encoding="utf-8")
    report = s3_wind.run_s3(nea, [extract])
    assert not report.identifiable_source and "not a source attribution" in report.statement
    assert len(report.boxes) == 3 and all(len(b.variants) == 2 for b in report.boxes)
    assert all(b.verdict in ("consistent", "inconsistent", "inconclusive") for b in report.boxes)
    assert all(c.passed for c in report.clocks) and report.precip["box-a"].max_mm_h == 0.0
    assert report.overall == "inconclusive" or report.overall in ("consistent", "inconsistent")
