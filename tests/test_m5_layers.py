"""Layer catalogue: states, coverage by day, point and wind readers return only file values."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from earthlab.m5.layers import LayerSpec, catalogue_json, read_fire_points, read_wind_vector


def spec(**over: object) -> LayerSpec:
    base: dict[str, object] = dict(
        layer_id="x", title="t", kind="points", state="available", product="p", version="1",
        unit="u", first_utc=datetime(2015, 9, 1, tzinfo=UTC),
        last_utc=datetime(2015, 9, 30, tzinfo=UTC), attribution="a", hindsight=True,
    )  # fmt: skip
    base.update(over)
    return LayerSpec(**base)


def test_only_available_layers_cover_a_day() -> None:
    assert spec().covers(date(2015, 9, 15)) and not spec().covers(date(2015, 10, 1))
    assert not spec(state="gated_out", reason="r").covers(date(2015, 9, 15))
    assert not spec(first_utc=None).covers(date(2015, 9, 15))
    with pytest.raises(ValidationError):
        spec(surprise=1)


def test_fire_points_are_exactly_the_file_rows_for_the_day(tmp_path: Path) -> None:
    f = tmp_path / "f.csv"
    f.write_text("latitude,longitude,acq_date,acq_time,frp,confidence,satellite\n"
                 "-2.1,114.0,2015-09-02,305,12.5,80,Terra\n"
                 "-2.2,114.1,2015-09-03,1405,3.0,20,Aqua\n")  # fmt: skip
    got = read_fire_points(f, date(2015, 9, 2))
    assert len(got) == 1 and got[0].time_utc == datetime(2015, 9, 2, 3, 5, tzinfo=UTC)
    assert got[0].frp_mw == 12.5 and read_fire_points(f, date(2015, 9, 4)) == []


def test_wind_vector_returns_file_value_or_none(tmp_path: Path) -> None:
    f = tmp_path / "e.json"
    hours = [
        {"time": "2015-09-01T00:00:00Z", "u_ms": 1.0, "v_ms": -2.0, "precip_mm": None},
        {"time": "2015-09-01T01:00:00Z", "u_ms": None, "v_ms": 1.0, "precip_mm": None},
    ]
    f.write_text(json.dumps({"series": [{"box_id": "box-a", "hours": hours}]}))
    at = datetime(2015, 9, 1, 0, 30, tzinfo=UTC)
    assert read_wind_vector(f, "box-a", at) == (1.0, -2.0)
    assert read_wind_vector(f, "box-a", datetime(2015, 9, 1, 1, tzinfo=UTC)) is None
    assert read_wind_vector(f, "box-a", datetime(2015, 9, 5, tzinfo=UTC)) is None
    with pytest.raises(ValueError, match="UTC"):
        read_wind_vector(f, "box-a", datetime(2015, 9, 1))


def test_catalogue_json_is_sorted_and_round_trips() -> None:
    out = catalogue_json([spec()])
    assert json.loads(out)[0]["layer_id"] == "x" and out.endswith("\n")
