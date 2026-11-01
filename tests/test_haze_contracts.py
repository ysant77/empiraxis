"""Haze dataset descriptors, the catalogue and the look-ahead guard on prediction features."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from earthlab.haze.catalogue import load_catalogue
from earthlab.haze.contracts import (
    DatasetDescriptor,
    EvidenceClass,
    FeatureSet,
    Permission,
    PredictorFeature,
    TimeRole,
)

ROOT = Path(__file__).resolve().parents[1]
ISSUE = datetime(2015, 9, 24, 0, 0, tzinfo=UTC)


def _descriptor(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "dataset_id": "synthetic-wind",
        "product": "synthetic",
        "variable": "10m wind",
        "unit": "m/s",
        "aoi": {"min_lon": 95.0, "min_lat": -6.0, "max_lon": 118.0, "max_lat": 4.0},
        "valid_start": "2015-09-01T00:00:00Z",
        "valid_end": "2015-11-01T00:00:00Z",
        "time_role": "reanalysis",
        "temporal_support": {"kind": "instantaneous", "step_hours": 1},
        "spatial_support": {"kind": "grid_cell", "resolution_m": 27750},
        "missingness": "none",
        "licence": "CC-BY 4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "size_estimate_bytes": 1,
        "size_is_estimate": True,
        "permission": "owner_approval",
        "max_evidence_class": "transport_plausibility",
        "method_suitability": "test",
        "synthetic": True,
    }
    base.update(overrides)
    return base


def test_catalogue_loads_and_only_the_nea_file_is_pinned() -> None:
    catalogue = load_catalogue(ROOT / "config" / "haze" / "datasets.yaml")
    pinned = [d.dataset_id for d in catalogue if d.permission is Permission.PINNED]
    assert pinned == ["nea-historical-1hr-pm25"]
    assert all(d.valid_start.tzinfo is UTC for d in catalogue)
    assert all(not d.synthetic for d in catalogue)
    era5 = next(d for d in catalogue if d.dataset_id.startswith("era5-single"))
    assert EvidenceClass.FORECAST not in {era5.max_evidence_class}
    assert "forecast feature" in era5.not_for


def test_catalogue_refuses_duplicates_and_bad_shape(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("datasets: []\n", encoding="utf-8")
    assert load_catalogue(empty) == ()
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="datasets"):
        load_catalogue(bad)
    twice = tmp_path / "twice.yaml"
    twice.write_text(json.dumps({"datasets": [_descriptor(), _descriptor()]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_catalogue(twice)


def test_descriptor_converts_to_utc_and_refuses_naive_times() -> None:
    d = DatasetDescriptor.model_validate(_descriptor(valid_start="2015-09-01T08:00:00+08:00"))
    assert d.valid_start == datetime(2015, 9, 1, 0, 0, tzinfo=UTC)
    with pytest.raises(ValidationError, match="naive"):
        DatasetDescriptor.model_validate(_descriptor(valid_start="2015-09-01T00:00:00"))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"extra_field": 1}, "Extra inputs"),
        ({"valid_end": "2015-08-01T00:00:00Z"}, "valid_end"),
        ({"time_role": "forecast"}, "issue_time"),
        ({"issue_time": "2015-09-01T00:00:00Z"}, "only a forecast"),
        ({"max_evidence_class": "causal_inference"}, "causal"),
        ({"max_evidence_class": "forecast"}, "archived forecast"),
        ({"licence_url": "http://example.org"}, "licence_url"),
    ],
)
def test_descriptor_refusals(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        DatasetDescriptor.model_validate(_descriptor(**overrides))


def _feature(role: TimeRole, valid: datetime, **extra: Any) -> PredictorFeature:
    return PredictorFeature(name=f"{role.value}-wind", time_role=role, valid_time=valid, **extra)


def test_reanalysis_feature_valid_after_issue_time_is_refused() -> None:
    leak = _feature(TimeRole.REANALYSIS, ISSUE + timedelta(hours=6))
    with pytest.raises(ValidationError, match="not known at issue time"):
        FeatureSet(issue_time=ISSUE, target_valid_time=ISSUE + timedelta(hours=6), features=(leak,))


def test_reanalysis_without_a_publication_time_is_refused() -> None:
    past = _feature(TimeRole.REANALYSIS, ISSUE - timedelta(hours=6))
    with pytest.raises(ValidationError, match="needs its publication time"):
        FeatureSet(issue_time=ISSUE, target_valid_time=ISSUE + timedelta(hours=6), features=(past,))
    known = _feature(
        TimeRole.REANALYSIS, ISSUE - timedelta(days=9), available_at=ISSUE - timedelta(days=1)
    )
    FeatureSet(issue_time=ISSUE, target_valid_time=ISSUE + timedelta(hours=6), features=(known,))


def test_forecast_feature_issued_after_prediction_issue_time_is_refused() -> None:
    late_run = _feature(
        TimeRole.FORECAST, ISSUE + timedelta(hours=6), source_issue_time=ISSUE + timedelta(hours=1)
    )
    with pytest.raises(ValidationError, match="not known at issue time"):
        FeatureSet(
            issue_time=ISSUE, target_valid_time=ISSUE + timedelta(hours=6), features=(late_run,)
        )


def test_observation_published_late_is_refused() -> None:
    late = _feature(TimeRole.OBSERVATION, ISSUE, available_at=ISSUE + timedelta(days=5))
    with pytest.raises(ValidationError, match="not known"):
        FeatureSet(issue_time=ISSUE, target_valid_time=ISSUE + timedelta(hours=1), features=(late,))


def test_as_of_safe_features_are_accepted() -> None:
    features = (
        _feature(TimeRole.OBSERVATION, ISSUE - timedelta(hours=1)),
        _feature(TimeRole.FORECAST, ISSUE + timedelta(hours=6), source_issue_time=ISSUE),
    )
    fs = FeatureSet(
        issue_time=ISSUE, target_valid_time=ISSUE + timedelta(hours=6), features=features
    )
    assert len(fs.features) == 2


def test_feature_set_structural_refusals() -> None:
    with pytest.raises(ValidationError, match="source issue time"):
        _feature(TimeRole.FORECAST, ISSUE)
    with pytest.raises(ValidationError, match="target must be valid after"):
        FeatureSet(issue_time=ISSUE, target_valid_time=ISSUE, features=())
