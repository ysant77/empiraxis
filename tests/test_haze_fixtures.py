"""The six synthetic haze adversarial fixtures: shape, labels and that their traps are real."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import pytest
import yaml
from pydantic import Field, ValidationError

from earthlab.contracts import Strict
from earthlab.haze.contracts import EvidenceClass, FeatureSet, PredictorFeature, TimeRole
from earthlab.haze.wind import blows_from_source, uv_from_wind, wind_from_uv

FIXTURES = Path(__file__).parent / "fixtures" / "haze"
NORMAL_BAND_MAX = 55
RAIN_REMOVAL_MM_PER_H = 1.0


class Outcome(StrEnum):
    QUALIFIED = "qualified"
    INCONCLUSIVE = "inconclusive"
    REFUSE = "refuse"


class Expected(Strict):
    outcome: Outcome
    max_evidence_class: EvidenceClass
    must_state: tuple[str, ...] = Field(min_length=1)
    forbidden_claims: tuple[str, ...] = Field(min_length=1)


class HazeFixture(Strict):
    id: str = Field(pattern=r"^HZ-DEV-\d{2}$")
    synthetic: Literal[True]
    split: Literal["development"]
    sealed_heldout: Literal[False]
    control: str
    question: str
    trap: str
    synthetic_inputs: dict[str, Any]
    expected: Expected


def _load() -> dict[str, HazeFixture]:
    loaded = [
        HazeFixture.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))
        for p in sorted(FIXTURES.glob("hz_dev_*.yaml"))
    ]
    return {f.id: f for f in loaded}


def test_six_unique_synthetic_development_fixtures() -> None:
    fixtures = _load()
    assert len(fixtures) == 6
    assert len({f.control for f in fixtures.values()}) == 6
    for fixture in fixtures.values():
        assert fixture.expected.max_evidence_class is not EvidenceClass.CAUSAL_INFERENCE


def test_schema_refuses_an_unlabelled_or_heldout_style_fixture() -> None:
    raw = yaml.safe_load((FIXTURES / "hz_dev_01_fire_upwind_no_rise.yaml").read_text("utf-8"))
    for key, value in (("synthetic", False), ("sealed_heldout", True), ("id", "HO-01")):
        with pytest.raises(ValidationError):
            HazeFixture.model_validate({**raw, key: value})


def test_fire_upwind_fixture_is_in_sector_with_no_pm25_rise() -> None:
    inputs = _load()["HZ-DEV-01"].synthetic_inputs
    for bearing, speed in zip(
        inputs["wind_from_deg_by_hour"], inputs["wind_speed_ms_by_hour"], strict=True
    ):
        reading = wind_from_uv(*uv_from_wind(speed, bearing))
        assert blows_from_source(reading, inputs["source_bearing_deg"], tolerance_deg=45.0)
    assert max(inputs["pm25_south_ug_m3_by_hour"]) <= NORMAL_BAND_MAX


def test_rain_fixture_has_washout_and_a_wind_shift() -> None:
    inputs = _load()["HZ-DEV-03"].synthetic_inputs
    assert max(inputs["rain_mm_per_h_on_path_by_6h"]) > RAIN_REMOVAL_MM_PER_H
    in_sector = [
        blows_from_source(
            wind_from_uv(*uv_from_wind(speed, bearing)), inputs["source_bearing_deg"], 45.0
        )
        for bearing, speed in zip(
            inputs["wind_from_deg_by_6h"], inputs["wind_speed_ms_by_6h"], strict=True
        )
    ]
    assert any(in_sector)
    assert not all(in_sector)


def test_visibility_fixture_pm25_is_in_the_normal_band() -> None:
    values = _load()["HZ-DEV-04"].synthetic_inputs["pm25_all_regions_ug_m3"]
    assert max(values.values()) <= NORMAL_BAND_MAX


def test_reanalysis_as_forecast_fixture_is_refused_by_the_contract() -> None:
    inputs = _load()["HZ-DEV-06"].synthetic_inputs
    feature = inputs["feature"]
    with pytest.raises(ValidationError, match="not known at issue time"):
        FeatureSet(
            issue_time=datetime.fromisoformat(inputs["issue_time_utc"]),
            target_valid_time=datetime.fromisoformat(inputs["target_valid_time_utc"]),
            features=(
                PredictorFeature(
                    name=feature["name"],
                    time_role=TimeRole(feature["time_role"]),
                    valid_time=datetime.fromisoformat(feature["valid_time_utc"]),
                ),
            ),
        )
