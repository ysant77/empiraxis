"""Rain units, no false zeros, QA masks, index maths and issue-time rules."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from earthlab.haze.wind import uv_from_wind, wind_from_uv
from earthlab.m5 import masks, units
from earthlab.m5.availability import LeakError, assert_issue_time_valid, latest_visible_end

T = datetime(2015, 10, 19, 6, tzinfo=UTC)


def test_era5_metres_to_mm_and_missing_stays_missing() -> None:
    assert units.era5_tp_m_to_mm(0.0012) == pytest.approx(1.2)
    assert units.era5_tp_m_to_mm(-1e-12) == 0.0
    assert math.isnan(units.era5_tp_m_to_mm(math.nan))
    with pytest.raises(ValueError):
        units.era5_tp_m_to_mm(-0.001)


def test_rate_is_multiplied_by_duration_before_summing() -> None:
    assert units.rate_to_accumulation_mm(4.0, 0.5) == 2.0
    assert units.hourly_from_half_hourly([4.0, 2.0]) == pytest.approx(3.0)
    with pytest.raises(ValueError):
        units.rate_to_accumulation_mm(-1.0, 0.5)
    with pytest.raises(ValueError):
        units.rate_to_accumulation_mm(1.0, 0.0)


def test_missing_half_hour_makes_the_hour_missing_not_zero() -> None:
    assert math.isnan(units.hourly_from_half_hourly([4.0, math.nan]))
    with pytest.raises(ValueError):
        units.hourly_from_half_hourly([1.0])


def test_fill_becomes_nan_not_zero() -> None:
    out = masks.with_fill_as_nan(np.array([1, -9999, 3]), -9999)
    assert np.isnan(out[1]) and out[0] == 1 and out[2] == 3


def test_coverage_mean_reports_fraction_and_refuses_thin_coverage() -> None:
    values = np.array([1.0, np.nan, 3.0, np.nan])
    got = masks.coverage_mean(values, 0.5)
    assert got.mean == 2.0 and got.valid_fraction == 0.5 and got.n_valid == 2
    assert math.isnan(masks.coverage_mean(values, 0.75).mean)
    assert math.isnan(masks.coverage_mean(np.full(3, np.nan), 0.1).mean)
    with pytest.raises(ValueError):
        masks.coverage_mean(values, 0.0)


def test_hls_fmask_bits() -> None:
    f = np.array([0, 1, 2, 4, 8, 16, 32, 64 + 128], dtype=np.uint8)
    clear = masks.hls_clear_land(f)
    # clear: 0, cirrus-only (1), high-aerosol pixel. Rejected: cloud, adjacent, shadow, snow, water
    assert clear.tolist() == [True, True, False, False, False, False, False, True]
    assert masks.hls_aerosol_level(f).tolist() == [0, 0, 0, 0, 0, 0, 0, 3]


def test_indices_keep_masks_and_reject_bad_denominators() -> None:
    nir = np.array([0.4, 0.4, 0.0, np.nan])
    swir = np.array([0.1, 0.1, 0.0, 0.1])
    valid = np.array([True, False, True, True])
    out = masks.nbr(nir, swir, valid)
    assert out[0] == pytest.approx(0.6)
    assert np.isnan(out[1]) and np.isnan(out[2]) and np.isnan(out[3])
    pre, post = np.array([0.6, np.nan]), np.array([0.1, 0.2])
    d = masks.dnbr(pre, post)
    assert d[0] == pytest.approx(0.5) and np.isnan(d[1])


def test_wind_vector_convention_round_trip() -> None:
    # A wind FROM the south-east (135 deg) blows toward the north-west: u < 0, v > 0.
    u, v = uv_from_wind(5.0, 135.0)
    assert u < 0 < v
    back = wind_from_uv(u, v)
    assert back.speed_ms == pytest.approx(5.0) and back.from_deg == pytest.approx(135.0)
    assert wind_from_uv(0.0, 0.0).from_deg is None


@pytest.mark.parametrize(("source", "hours", "ok"), [
    ("nea_pm25", 2, True), ("nea_pm25", 1, False),
    ("firms_modis_sp", 3, True), ("firms_modis_sp", 2, False),
    ("imerg_early", 4, True), ("imerg_early", 3, False),
    ("imerg_late", 13, False), ("imerg_late", 14, True),
    ("smap_l3", 6, False),
])  # fmt: skip
def test_issue_time_rule(source: str, hours: int, ok: bool) -> None:
    obs_end = T - timedelta(hours=hours)
    if ok:
        assert_issue_time_valid(source, obs_end, T)
    else:
        with pytest.raises(LeakError):
            assert_issue_time_valid(source, obs_end, T)


@pytest.mark.parametrize("source", ["era5", "mcd64a1", "hls_archive", "maiac_061"])
def test_hindsight_sources_never_pass(source: str) -> None:
    with pytest.raises(LeakError):
        assert_issue_time_valid(source, T - timedelta(days=400), T)
    with pytest.raises(LeakError):
        latest_visible_end(source, T)


def test_latest_visible_end_matches_latency() -> None:
    assert latest_visible_end("imerg_early", T) == T - timedelta(hours=4)


def test_imerg_final_is_not_readable_for_a_recent_window_at_t_plus_six() -> None:
    """IMERG Final needs about 106 days. A window ending 6 h before T is a leak."""
    from datetime import UTC, datetime, timedelta

    import pytest

    from earthlab.m5.availability import LeakError, assert_issue_time_valid

    issue = datetime(2015, 10, 20, 12, tzinfo=UTC)
    for hours_back in (6, 24, 24 * 100):
        with pytest.raises(LeakError):
            assert_issue_time_valid("imerg_final", issue - timedelta(hours=hours_back), issue)
    assert_issue_time_valid("imerg_final", issue - timedelta(hours=24 * 107), issue)
    assert_issue_time_valid("imerg_early", issue - timedelta(hours=5), issue)
    with pytest.raises(LeakError):
        assert_issue_time_valid("smap_l3", issue - timedelta(hours=6), issue)
