"""H0 descriptive PM2.5 summary on synthetic NEA-format data, and the fallback report."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from haze_synthetic import START_SGT, calm_air, episode, write_nea

from earthlab.contracts import SGT, Region
from earthlab.haze.cli import load_h0
from earthlab.haze.contracts import EvidenceClass
from earthlab.haze.evidence import ClaimRefused, Provenance, check_claim, output_digest
from earthlab.haze.fallback import WIND_STATEMENT, fallback_report
from earthlab.haze.h0 import find_events, is_control_hour

EPISODE = datetime(2015, 9, 24, 20, 0, tzinfo=SGT)


def test_event_runs_need_three_contiguous_hours_above_55() -> None:
    hot = {Region.WEST: 120.0, Region.EAST: 40.0}
    t0 = datetime(2015, 9, 10, tzinfo=SGT)
    hourly = [
        (t0, hot),
        (t0 + timedelta(hours=1), hot),  # two hours only: not an event
        (t0 + timedelta(hours=2), {Region.WEST: 50.0}),
        (t0 + timedelta(hours=3), hot),
        (t0 + timedelta(hours=4), hot),
        (t0 + timedelta(hours=6), hot),  # a gap at hour 5 ends the run
        (t0 + timedelta(hours=7), hot),
        (t0 + timedelta(hours=8), {Region.SOUTH: 200.0}),
    ]
    events = find_events(hourly)
    assert len(events) == 1
    event = events[0]
    assert (event.start, event.hours, event.end) == (
        t0 + timedelta(hours=6),
        3,
        t0 + timedelta(hours=9),
    )
    assert (event.peak_ug_m3, event.peak_region) == (200.0, Region.SOUTH)
    assert event.regions_above == (Region.SOUTH, Region.WEST)


def test_control_hour_needs_all_regions_at_or_below_55() -> None:
    assert is_control_hour(dict(zip(Region, (30.0, 40.0, 55.0, 20.0, 10.0), strict=True)))
    assert not is_control_hour({Region.NORTH: 30.0})
    assert not is_control_hour(dict(zip(Region, (30.0, 40.0, 56.0, 20.0, 10.0), strict=True)))


def test_describe_counts_bands_missing_hours_and_events(tmp_path: Path) -> None:
    def rule(moment: datetime) -> tuple[float | None, ...]:
        if moment == START_SGT + timedelta(hours=5):
            return (None, 30.0, 30.0, 30.0, 30.0)
        return episode(EPISODE, 6, 260.0)(moment)

    report = load_h0(write_nea(tmp_path / "nea", rule))
    north = next(r for r in report.regions if r.region is Region.NORTH)
    assert (north.expected_hours, north.observed_hours, north.missing_hours) == (1464, 1463, 1)
    assert north.hours_above == {"elevated": 6, "high": 6, "very_high": 6}
    assert north.max_ug_m3 == 260.0 and north.max_at == EPISODE
    assert [(e.start, e.hours) for e in report.events] == [(EPISODE, 6)]
    assert report.event_hours == 6 and report.control_hours == 1464 - 6 - 1
    assert len(report.daily) == 61 * 5
    assert report.provenance.evidence_class is EvidenceClass.OBSERVATION
    assert report.provenance.sources[0].dataset_id == "synthetic-nea-pm25"


def test_h0_is_deterministic(tmp_path: Path) -> None:
    folder = write_nea(tmp_path / "nea", calm_air)
    assert output_digest(load_h0(folder)) == output_digest(load_h0(folder))


def test_fallback_keeps_observation_class_and_never_checks_wind(tmp_path: Path) -> None:
    h0 = load_h0(write_nea(tmp_path / "nea", episode(EPISODE, 4, 120.0)))
    report = fallback_report(h0, "ERA5 missed the stop rule")
    assert report.provenance.evidence_class is EvidenceClass.OBSERVATION
    assert report.wind_statement == WIND_STATEMENT
    assert [e.wind_status for e in report.events] == ["not_checked"]
    assert report.h0_digest == output_digest(h0)
    south_sumatra = next(g for g in report.geometry if g.box_id == "box-b")
    assert 150 < south_sumatra.bearing_deg < 200
    assert any("not checked" in text for text in report.provenance.limitations)


def test_claim_ceiling_refuses_causal_and_higher_classes(tmp_path: Path) -> None:
    assert check_claim(EvidenceClass.OBSERVATION, EvidenceClass.TRANSPORT_PLAUSIBILITY)
    with pytest.raises(ClaimRefused, match="exceeds"):
        check_claim(EvidenceClass.HINDCAST, EvidenceClass.TRANSPORT_PLAUSIBILITY)
    with pytest.raises(ClaimRefused, match="causal"):
        check_claim(EvidenceClass.CAUSAL_INFERENCE, EvidenceClass.FORECAST)
    provenance = load_h0(write_nea(tmp_path / "nea")).provenance
    with pytest.raises(ValueError, match="causal"):
        Provenance.model_validate({**provenance.model_dump(), "evidence_class": "causal_inference"})
