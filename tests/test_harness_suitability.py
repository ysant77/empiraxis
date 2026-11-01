"""Dataset suitability and the alignment preflight. It must fail closed."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from suitability_helpers import AOI, END, START, plan, profile

from earthlab.cases.models import BoundingBox
from earthlab.harness.suitability import (
    Code,
    TimestampError,
    check_timestamps,
    parse_timestamp,
    preflight,
)


def codes(report: object) -> set[Code]:
    return {f.code for f in report.findings}  # type: ignore[attr-defined]


def test_malformed_naive_and_repeated_stamps_are_flagged() -> None:
    found = check_timestamps(
        "nea",
        ["2015-09-01T00:00:00+08:00", "yesterday", "2015-09-01 01:00", "2015-09-01T00:00:00+08:00"],
    )
    assert {f.code for f in found} == {
        Code.MALFORMED_TIMESTAMP, Code.NAIVE_TIMESTAMP, Code.DUPLICATE_TIMESTAMP,
    }  # fmt: skip
    assert all(f.blocking for f in found)
    assert parse_timestamp("2015-09-01T08:00:00+08:00") == datetime(2015, 9, 1, tzinfo=UTC)
    with pytest.raises(TimestampError):
        parse_timestamp("2015-13-45T00:00:00Z")


def test_an_issue_time_arm_without_available_at_is_not_alignable() -> None:
    nea = profile(
        dataset_id="nea", data_kind="observation", availability="unknown",
        allowed_evidence=("historical_research",),
    )  # fmt: skip
    report = preflight(plan(arm="issue_time_forecast", inputs=("nea",)), [nea])
    assert report.verdict == "not_alignable" and Code.MISSING_AVAILABLE_AT in codes(report)


def test_reanalysis_is_never_an_issue_time_input() -> None:
    report = preflight(plan(arm="issue_time_forecast"), [profile()])
    assert report.verdict == "not_alignable" and Code.REANALYSIS_AS_FORECAST in codes(report)
    with pytest.raises(ValidationError):
        profile(allowed_evidence=("issue_time_forecast",))


def test_reanalysis_supports_a_labelled_hindsight_diagnostic() -> None:
    report = preflight(plan(), [profile()])
    assert report.verdict == "aligned_with_caveats" and codes(report) == {Code.HINDSIGHT_LABEL}


def test_logged_and_modelled_availability_need_their_facts() -> None:
    with pytest.raises(ValidationError):
        profile(availability="logged")
    with pytest.raises(ValidationError):
        profile(availability="modelled")
    modelled = profile(availability="modelled", latency_hours=6.0, data_kind="observation")
    report = preflight(plan(arm="issue_time_forecast"), [modelled])
    assert report.verdict == "aligned_with_caveats" and Code.MODELLED_AVAILABILITY in codes(report)
    logged = profile(
        availability="logged", available_at_field="available_at", data_kind="issued_forecast"
    )
    assert preflight(plan(arm="issue_time_forecast"), [logged]).verdict == "aligned"


def test_a_unit_mismatch_blocks_the_join() -> None:
    wrong = profile(variables=(profile().variables[0].model_copy(update={"unit": "km h-1"}),))
    assert Code.UNIT_MISMATCH in codes(preflight(plan(), [wrong]))


def test_data_outside_the_task_area_or_window_blocks_the_join() -> None:
    far = BoundingBox(min_lon=10, min_lat=10, max_lon=11, max_lat=11)
    assert Code.OUT_OF_AOI in codes(preflight(plan(), [profile(area=far)]))
    half = BoundingBox(min_lon=102.5, min_lat=-4.5, max_lon=104.0, max_lat=-1.0)
    assert Code.AOI_PARTIAL in codes(preflight(plan(), [profile(area=half)]))
    assert Code.AOI_UNKNOWN in codes(preflight(plan(), [profile(area=None)]))
    late = datetime(2016, 1, 1, tzinfo=UTC)
    assert Code.OUT_OF_TIME in codes(preflight(plan(), [profile(first_time=late, last_time=late)]))
    short = profile(last_time=datetime(2015, 10, 1, tzinfo=UTC))
    assert Code.TIME_PARTIAL in codes(preflight(plan(), [short]))


def test_misaligned_time_and_space_supports_block_the_join() -> None:
    assert Code.MISALIGNED_CADENCE in codes(preflight(plan(), [profile(cadence_hours=24.0)]))
    assert Code.MISALIGNED_CADENCE in codes(
        preflight(plan(target_cadence_hours=5.0), [profile(cadence_hours=2.0)])
    )
    region = profile(spatial_support="region")
    assert preflight(plan(), [region]).verdict == "not_alignable"
    ok = preflight(plan(spatial_aggregation="mean of cells in the region"), [region])
    assert ok.verdict == "aligned_with_caveats"
    assert Code.TIME_CONVENTION_UNKNOWN in codes(preflight(plan(), [profile(valid_time="unknown")]))


def test_cloud_and_missing_observations_block_optical_data() -> None:
    optical = profile(optical=True, data_kind="observation", missing_fraction=0.1)
    assert Code.CLOUD_MASK_MISSING in codes(preflight(plan(), [optical]))
    gappy = profile(missing_fraction=0.55)
    assert Code.NO_OBSERVATION in codes(preflight(plan(), [gappy]))
    unknown = profile(missing_fraction=None)
    report = preflight(plan(), [unknown])
    assert Code.MISSINGNESS_UNKNOWN in codes(report) and report.verdict != "not_alignable"


def test_unverified_absent_and_unlisted_inputs_block_the_join() -> None:
    assert Code.NOT_ACQUIRED in codes(preflight(plan(), [profile(local_state="not_acquired")]))
    assert Code.NOT_VERIFIED in codes(preflight(plan(), [profile(local_state="unverified")]))
    assert Code.NOT_ACQUIRED in codes(preflight(plan(inputs=("missing",)), [profile()]))


def test_an_input_window_that_reaches_the_evaluation_period_is_leakage() -> None:
    report = preflight(plan(evaluation_start=START), [profile()])
    assert Code.LEAKAGE in codes(report) and report.verdict == "not_alignable"
    assert Code.LEAKAGE not in codes(preflight(plan(evaluation_start=END), [profile()]))


def test_a_verified_file_needs_a_hash_and_a_zone() -> None:
    with pytest.raises(ValidationError):
        profile(local_sha256=None)
    with pytest.raises(ValidationError):
        profile(first_time=datetime(2015, 9, 1))
    assert AOI.min_lon < AOI.max_lon and START < END
