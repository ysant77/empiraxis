"""Profiles and plans for the suitability, acquisition and S4 tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from earthlab.cases.models import BoundingBox
from earthlab.harness.suitability import DatasetSuitabilityV1, JoinPlanV1, VariableSpec

AOI = BoundingBox(min_lon=102.5, min_lat=-4.5, max_lon=106.5, max_lat=-1.0)
START, END = datetime(2015, 9, 1, tzinfo=UTC), datetime(2015, 11, 1, tzinfo=UTC)
SHA = "a" * 64


def profile(**change: Any) -> DatasetSuitabilityV1:
    base: dict[str, Any] = dict(
        dataset_id="era5-sl", revision="final", source_url="https://example.org/era5",
        variables=(VariableSpec(name="u10", unit="m s-1"),), area=AOI, first_time=START,
        last_time=END, cadence_hours=1.0, spatial_support="grid_cell", event_time="instant",
        valid_time="instant", data_kind="reanalysis", availability="not_applicable",
        license="CC-BY 4.0", local_state="verified", local_sha256=SHA, permission="covered_signed",
        allowed_evidence=("hindsight_diagnostic",), missing_fraction=0.0,
    )  # fmt: skip
    return DatasetSuitabilityV1(**(base | change))


def plan(**change: Any) -> JoinPlanV1:
    base: dict[str, Any] = dict(
        target_id="task", arm="hindsight_diagnostic", inputs=("era5-sl",), aoi=AOI,
        window_start=START, window_end=END, expected_units={"u10": "m s-1"},
        target_cadence_hours=1.0, target_support="grid_cell",
    )  # fmt: skip
    return JoinPlanV1(**(base | change))
