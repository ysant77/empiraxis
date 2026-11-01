"""H1 lagged sector diagnostic on synthetic wind, rain and fire inputs only."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from haze_synthetic import SYNTHETIC_REF, met_series, steady, write_nea

from earthlab.contracts import SGT
from earthlab.data.nea_pm25 import load_pm25
from earthlab.data.snapshot import open_snapshot
from earthlab.haze import fires as fires_mod
from earthlab.haze.base_rate import _rate, run_base_rate
from earthlab.haze.cli import load_h0, read_fires
from earthlab.haze.contracts import EvidenceClass
from earthlab.haze.evidence import SourceRef, output_digest
from earthlab.haze.fires import FireDetection
from earthlab.haze.geometry import H1_SOURCE_BOXES
from earthlab.haze.h0 import H0Report
from earthlab.haze.h1 import control_labels, run_h1, time_sensitive_boxes
from earthlab.haze.sector import (
    H1Params,
    MetHour,
    TransportStatus,
    combine,
    lag_check,
)
from earthlab.haze.timebase import HourConvention
from earthlab.haze.wind import uv_from_wind

FIXTURES = Path(__file__).parent / "fixtures" / "haze"
BOX_B = H1_SOURCE_BOXES[1]
ONSET = datetime(2015, 9, 20, 12, tzinfo=UTC)
PARAMS = H1Params()
EVENTS = [datetime(2015, 9, d, 20, tzinfo=SGT) for d in (10, 17, 24, 30)] + [
    datetime(2015, 10, 8, 20, tzinfo=SGT)
]


def _series(rule: Sequence[tuple[float, float, float | None]]) -> dict[datetime, MetHour]:
    """Hours before ONSET, oldest first: (speed, from_deg, rain_mm)."""
    out: dict[datetime, MetHour] = {}
    for i, (speed, from_deg, rain) in enumerate(reversed(rule), start=1):
        u, v = uv_from_wind(speed, from_deg)
        moment = ONSET - timedelta(hours=i)
        out[moment] = MetHour(time=moment, u_ms=u, v_ms=v, precip_mm=rain)
    return out


def test_lag_check_consistent_inconsistent_and_inconclusive() -> None:
    bearing = BOX_B.bearing_deg
    good = lag_check(_series([(8.0, bearing, 0.0)] * 24), BOX_B, ONSET, 24, PARAMS)
    assert good.status is TransportStatus.CONSISTENT and good.in_sector_fraction == 1.0
    assert good.advected_km == pytest.approx(8.0 * 3.6 * 24)
    opposite = lag_check(_series([(8.0, bearing + 180, 0.0)] * 24), BOX_B, ONSET, 24, PARAMS)
    assert opposite.status is TransportStatus.INCONSISTENT and opposite.advected_km < 0
    slow = lag_check(_series([(1.0, bearing, 0.0)] * 24), BOX_B, ONSET, 24, PARAMS)
    assert slow.status is TransportStatus.INCONSISTENT  # in sector, too slow to arrive
    wet = lag_check(
        _series([(8.0, bearing, 0.0)] * 23 + [(8.0, bearing, 2.5)]), BOX_B, ONSET, 24, PARAMS
    )
    assert wet.rain_affected and wet.status is TransportStatus.INCONCLUSIVE
    calm = lag_check(_series([(0.1, bearing, 0.0)] * 24), BOX_B, ONSET, 24, PARAMS)
    assert calm.calm_hours == 24 and calm.status is TransportStatus.INCONCLUSIVE
    gappy = lag_check(_series([(8.0, bearing, 0.0)] * 20), BOX_B, ONSET, 24, PARAMS)
    assert gappy.missing_hours == 4 and gappy.status is TransportStatus.INCONCLUSIVE


def test_combine_prefers_consistent_then_inconclusive() -> None:
    bearing = BOX_B.bearing_deg
    ok = lag_check(_series([(8.0, bearing, 0.0)] * 24), BOX_B, ONSET, 24, PARAMS)
    bad = lag_check(_series([(8.0, bearing + 180, 0.0)] * 24), BOX_B, ONSET, 24, PARAMS)
    unsure = lag_check(_series([(0.1, bearing, 0.0)] * 24), BOX_B, ONSET, 24, PARAMS)
    assert combine([bad, ok]) is TransportStatus.CONSISTENT
    assert combine([bad, unsure]) is TransportStatus.INCONCLUSIVE
    assert combine([bad]) is TransportStatus.INCONSISTENT


def test_rain_fixture_hz_dev_03_is_inconclusive() -> None:
    raw = yaml.safe_load((FIXTURES / "hz_dev_03_rain_wind_shift.yaml").read_text("utf-8"))
    inputs = raw["synthetic_inputs"]
    blocks = zip(
        inputs["wind_from_deg_by_6h"],
        inputs["wind_speed_ms_by_6h"],
        inputs["rain_mm_per_h_on_path_by_6h"],
        strict=True,
    )
    hours = [(speed, bearing, rain) for bearing, speed, rain in blocks for _ in range(6)]
    kalimantan = H1_SOURCE_BOXES[2]
    check = lag_check(_series(hours), kalimantan, ONSET, 36, PARAMS)
    assert check.rain_affected and check.status is TransportStatus.INCONCLUSIVE
    assert raw["expected"]["outcome"] == "inconclusive"


def _h0(tmp_path: Path, starts: list[datetime]) -> H0Report:
    def rule(moment: datetime) -> tuple[float | None, ...]:
        for start in starts:
            if start <= moment < start + timedelta(hours=6):
                return (150.0,) * 5
        return (30.0,) * 5

    return load_h0(write_nea(tmp_path / "nea", rule))


def _fires(box_index: int) -> dict[str, list[FireDetection]]:
    source = H1_SOURCE_BOXES[box_index]
    lat, lon = source.centre
    first = datetime(2015, 8, 28, tzinfo=UTC)
    detections = [
        FireDetection(time=first + timedelta(hours=6 * i), lat=lat, lon=lon, confidence=80)
        for i in range(260)
    ]
    return {source.box_id: detections}


def test_run_h1_labels_transport_plausibility_and_counts_controls(tmp_path: Path) -> None:
    h0 = _h0(tmp_path, EVENTS)
    report = run_h1(h0, met_series(steady(8.0)), _fires(1), (SYNTHETIC_REF,), synthetic=True)
    assert report.provenance.evidence_class is EvidenceClass.TRANSPORT_PLAUSIBILITY
    assert report.provenance.synthetic
    assert report.provenance.sources[0].dataset_id == "synthetic-nea-pm25"
    events = [o for o in report.onsets if o.kind == "event"]
    assert [o.label_sgt for o in events] == EVENTS
    assert events[0].onset_utc == datetime(2015, 9, 10, 11, tzinfo=UTC)  # hour ending 20:00 SGT
    by_box = {s.box_id: s for s in report.summaries}
    # Wind always blows from every box, so events are no more often consistent than controls.
    assert by_box["box-b"].association == "not_higher"
    controls = {c.control_id: c for c in report.negative_controls}
    assert controls["fire_upwind_no_pm25_rise"].count == by_box["box-b"].control_onsets
    assert controls["pm25_rise_without_upwind_detections"].count == 0
    assert controls["haze_looking_visibility_normal_pm25"].count is None
    notes = " ".join(n for o in events for b in o.boxes for n in b.notes)
    assert "not attribution" in notes and "not no fires" in notes
    assert not any(
        "caused" in text.lower() for text in report.provenance.limitations if "not" not in text
    )


def test_association_is_higher_only_when_wind_turns_for_events(tmp_path: Path) -> None:
    h0 = _h0(tmp_path, EVENTS)
    event_utc = [e.astimezone(UTC) - timedelta(hours=1) for e in EVENTS]

    def rule(moment: datetime, bearing: float) -> tuple[float, float, float]:
        near = any(start - timedelta(hours=72) <= moment < start for start in event_utc)
        return (8.0, bearing if near else bearing + 180, 0.0)

    report = run_h1(h0, met_series(rule), {}, (SYNTHETIC_REF,))
    assert {s.association for s in report.summaries} == {"higher_in_events"}
    controls = {c.control_id: c for c in report.negative_controls}
    assert controls["pm25_rise_without_upwind_detections"].count == len(EVENTS)


def test_rain_makes_every_box_inconclusive_and_too_few_onsets_are_insufficient(
    tmp_path: Path,
) -> None:
    h0 = _h0(tmp_path, EVENTS[:2])
    report = run_h1(h0, met_series(steady(8.0, rain=3.0)), {}, (SYNTHETIC_REF,))
    statuses = {b.status for o in report.onsets for b in o.boxes}
    assert statuses == {TransportStatus.INCONCLUSIVE}
    assert {s.association for s in report.summaries} == {"insufficient"}
    controls = {c.control_id: c for c in report.negative_controls}
    assert controls["rain_or_wind_shift"].count == 2


def test_missing_wind_series_and_determinism_and_conventions(tmp_path: Path) -> None:
    h0 = _h0(tmp_path, EVENTS)
    met = met_series(steady(8.0))
    with pytest.raises(ValueError, match="fallback"):
        run_h1(h0, {"box-a": met["box-a"]}, {}, (SYNTHETIC_REF,))
    first = run_h1(h0, met, {}, (SYNTHETIC_REF,))
    assert output_digest(first) == output_digest(run_h1(h0, met, {}, (SYNTHETIC_REF,)))
    beginning = run_h1(h0, met, {}, (SYNTHETIC_REF,), HourConvention.HOUR_BEGINNING)
    assert time_sensitive_boxes(first, beginning) == []


def test_control_labels_skip_hours_near_events(tmp_path: Path) -> None:
    h0 = _h0(tmp_path, [datetime(2015, 9, 15, 10, tzinfo=SGT)])
    labels = control_labels(h0)
    assert len(labels) == 61 - 3  # Sep 14, 15 and 16 lie within 24 h of the event
    assert all(label.hour == 14 for label in labels)
    assert datetime(2015, 9, 15, 14, tzinfo=SGT) not in labels


def test_a_constant_wind_shows_that_a_pass_says_nothing_about_haze(tmp_path: Path) -> None:
    h0 = _h0(tmp_path, EVENTS)
    snapshot, path = open_snapshot(tmp_path / "nea")
    report = run_base_rate(h0, load_pm25(path, snapshot), met_series(steady(8.0)))
    box = next(b for b in report.boxes if b.box_id == BOX_B.box_id)
    groups = {g.group: g for g in box.groups}
    assert groups["all_hours"].rate == 1.0 and groups["clean_at_or_below_55"].rate == 1.0
    assert groups["above_150"].hours == 0 and groups["above_150"].rate is None
    assert report.hours_checked == groups["all_hours"].hours > 0


def test_undecided_hours_leave_no_rate() -> None:
    assert _rate("x", [TransportStatus.INCONCLUSIVE]).rate is None


def test_firms_option_order_does_not_change_the_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = []
    for box in ("box-b", "box-a"):
        path = tmp_path / f"{box}.json"
        path.write_text(json.dumps({"asset_id": f"firms-{box}"}), encoding="utf-8")
        paths.append(path)
    monkeypatch.setattr(
        fires_mod,
        "read_manifest",
        lambda p: ([], (SourceRef(dataset_id=p.stem, file="f", sha256="0" * 64),)),
    )
    assert read_fires(paths) == read_fires(paths[::-1])
    assert [r.dataset_id for r in read_fires(paths)[1]] == ["box-a", "box-b"]
