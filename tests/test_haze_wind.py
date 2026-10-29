"""Wind geometry and the NEA-to-UTC time base: conventions, wraps and date changes."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from earthlab.contracts import SGT
from earthlab.haze.timebase import HourConvention, nea_label_to_utc_interval, to_utc
from earthlab.haze.wind import (
    WindReading,
    angular_difference,
    blows_from_source,
    downwind_unit_vector,
    great_circle_km,
    initial_bearing,
    normalise_bearing,
    uv_from_wind,
    wind_from_uv,
)

# (wind-from bearing, expected downwind (east, north)): a north wind blows to the south.
CARDINALS = [(0.0, (0.0, -1.0)), (90.0, (-1.0, 0.0)), (180.0, (0.0, 1.0)), (270.0, (1.0, 0.0))]


@pytest.mark.parametrize(("from_deg", "expected"), CARDINALS)
def test_downwind_vector_points_away_from_the_source_bearing(
    from_deg: float, expected: tuple[float, float]
) -> None:
    assert downwind_unit_vector(from_deg) == expected


@pytest.mark.parametrize(("from_deg", "expected"), CARDINALS)
def test_uv_round_trip_for_cardinals(from_deg: float, expected: tuple[float, float]) -> None:
    u, v = uv_from_wind(5.0, from_deg)
    assert (u, v) == (5.0 * expected[0], 5.0 * expected[1])
    reading = wind_from_uv(u, v)
    assert reading.speed_ms == pytest.approx(5.0)
    assert reading.from_deg == pytest.approx(from_deg)


def test_southwesterly_has_positive_u_and_v() -> None:
    u, v = uv_from_wind(math.sqrt(2), 225.0)
    assert u == pytest.approx(1.0)
    assert v == pytest.approx(1.0)


def test_calm_wind_has_no_direction() -> None:
    assert wind_from_uv(0.0, 0.0) == WindReading(speed_ms=0.0, from_deg=None)
    calm = wind_from_uv(0.2, -0.3)
    assert calm.is_calm
    assert not blows_from_source(calm, 180.0, tolerance_deg=180.0)


def test_bearing_wrap_at_0_and_360() -> None:
    assert normalise_bearing(360.0) == 0.0
    assert normalise_bearing(-0.0) == 0.0
    assert normalise_bearing(-1e-20) == 0.0
    assert normalise_bearing(-90.0) == 270.0
    assert normalise_bearing(720.5) == pytest.approx(0.5)
    # A north wind with a tiny westward U lies just west of north, never at 360.
    reading = wind_from_uv(1e-9, -5.0)
    assert reading.from_deg is not None
    assert 0.0 <= reading.from_deg < 360.0
    assert angular_difference(359.0, 1.0) == pytest.approx(2.0)
    assert angular_difference(0.0, 180.0) == pytest.approx(180.0)


def test_non_finite_input_is_refused() -> None:
    with pytest.raises(ValueError, match="finite"):
        normalise_bearing(math.nan)
    with pytest.raises(ValueError, match="finite"):
        wind_from_uv(math.inf, 0.0)
    with pytest.raises(ValueError, match="speed"):
        uv_from_wind(-1.0, 90.0)
    with pytest.raises(ValueError, match="tolerance"):
        blows_from_source(WindReading(speed_ms=3.0, from_deg=10.0), 0.0, tolerance_deg=200.0)


def test_bearing_and_distance_along_the_equator() -> None:
    assert initial_bearing(0.0, 100.0, 0.0, 110.0) == pytest.approx(90.0)
    assert initial_bearing(0.0, 110.0, 0.0, 100.0) == pytest.approx(270.0)
    assert great_circle_km(0.0, 100.0, 0.0, 101.0) == pytest.approx(111.195, abs=0.01)


def test_bearing_due_south_across_the_equator() -> None:
    assert initial_bearing(1.0, 104.0, -1.0, 104.0) == pytest.approx(180.0)
    assert initial_bearing(-1.0, 104.0, 1.0, 104.0) == pytest.approx(0.0, abs=1e-9)


def test_south_sumatra_lies_sse_and_needs_a_sse_wind() -> None:
    bearing = initial_bearing(1.35, 103.82, -2.99, 104.76)
    assert 160.0 < bearing < 175.0
    assert 480.0 < great_circle_km(1.35, 103.82, -2.99, 104.76) < 510.0
    sse = wind_from_uv(*uv_from_wind(6.0, 165.0))
    east = wind_from_uv(*uv_from_wind(6.0, 105.0))
    assert blows_from_source(sse, bearing, tolerance_deg=45.0)
    assert not blows_from_source(east, bearing, tolerance_deg=45.0)


def test_morning_sgt_label_falls_on_the_previous_utc_date() -> None:
    label = datetime(2015, 10, 1, 7, 0)
    start, end = nea_label_to_utc_interval(label, HourConvention.HOUR_ENDING)
    assert (start, end) == (
        datetime(2015, 9, 30, 22, 0, tzinfo=UTC),
        datetime(2015, 9, 30, 23, 0, tzinfo=UTC),
    )
    start, end = nea_label_to_utc_interval(label, HourConvention.HOUR_BEGINNING)
    assert (start, end) == (
        datetime(2015, 9, 30, 23, 0, tzinfo=UTC),
        datetime(2015, 10, 1, 0, 0, tzinfo=UTC),
    )


def test_midnight_label_crosses_month_end() -> None:
    label = datetime(2015, 11, 1, 0, 0, tzinfo=SGT)
    start, _ = nea_label_to_utc_interval(label, HourConvention.HOUR_ENDING)
    assert start == datetime(2015, 10, 31, 15, 0, tzinfo=UTC)


def test_time_base_refuses_naive_and_off_hour_times() -> None:
    with pytest.raises(ValueError, match="naive"):
        to_utc(datetime(2015, 9, 25, 12, 0))
    with pytest.raises(ValueError, match="on the hour"):
        nea_label_to_utc_interval(datetime(2015, 9, 25, 12, 30), HourConvention.HOUR_ENDING)
