"""The registry is the critic's only source of dataset facts; plan-level outcomes are typed."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from plan_helpers import ROOT, dataset, errors, method, raw, registry, review
from pydantic import ValidationError

from earthlab.cases.loader import load_case
from earthlab.cases.models import (
    ApprovalAction,
    BoundingBox,
    EvidenceClaim,
    ObservationStatus,
    ScientificVariable,
    StudyArea,
    StudyPeriod,
)
from earthlab.planning import CheckId, InvestigationPlan, candidates_from_case
from earthlab.planning.outcomes import gate_refusal, reportable_values
from earthlab.planning.registry import PROFILES_FILE, load_profiles
from earthlab.planning.vocab import PlanAction

C = CheckId
KALIMANTAN = ROOT / "config" / "cases" / "kalimantan-2015-burned-area.yaml"
MCD64A1 = "mcd64a1-061-kalimantan-2015"


def _manifest() -> dict[str, Any]:
    path = ROOT / "data" / "kalimantan-2015" / f"{MCD64A1}.manifest.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def test_candidates_from_case_joins_asset_profile_and_manifest() -> None:
    case_file = load_case(KALIMANTAN, ROOT)
    profiles = load_profiles(ROOT / PROFILES_FILE)
    records = {c.dataset_id: c for c in candidates_from_case(case_file, profiles)}
    assert records[MCD64A1].valid_fraction_by_period == ()
    measured = candidates_from_case(case_file, profiles, {MCD64A1: _manifest()})
    mcd = next(c for c in measured if c.dataset_id == MCD64A1)
    assert [p.valid_fraction for p in mcd.valid_fraction_by_period] == [0.9701, 0.4597]
    assert mcd.product_kind == "derived_product"
    assert mcd.sha256 == case_file.assets[MCD64A1].sha256


def test_a_product_without_a_profile_is_refused() -> None:
    with pytest.raises(ValueError, match="no planning profile"):
        candidates_from_case(load_case(KALIMANTAN, ROOT), {})


def test_registry_rejects_duplicates_and_has_a_stable_digest() -> None:
    real = registry()
    assert real.digest() == registry().digest()
    with pytest.raises(ValueError, match="already registered"):
        real.with_candidates([real.candidates[MCD64A1]])


def test_valid_fraction_follows_the_plan_months() -> None:
    record = registry().candidates[MCD64A1]

    def month(start: int, end: int) -> StudyPeriod:
        return StudyPeriod(
            start=datetime(2015, start, 1, tzinfo=UTC),
            end=datetime(2015, end, 1, tzinfo=UTC),
            local_zone="UTC",
        )

    assert record.valid_fraction_for(month(9, 10)) == 0.9701
    assert record.valid_fraction_for(month(9, 11)) == 0.4597
    assert record.valid_fraction_for(month(11, 12)) is None


def test_better_claimed_coverage_is_a_mismatch_and_is_ignored() -> None:
    plan = raw("kalimantan-2015-10-failed-coverage")
    report = review(plan)
    assert C.REGISTRY_MISMATCH in report.checks("error")
    assert C.DATA_COVERAGE in report.checks("error")
    plan = raw("kalimantan-2015-09-burned-area")
    dataset(plan, MCD64A1)["coverage"]["end"] = "2016-01-01T00:00:00Z"
    paths = {f.field_path for f in review(plan).findings}
    assert f"data_candidates[{MCD64A1}].coverage" in paths


def test_unregistered_dataset_is_an_error_and_counts_as_unavailable() -> None:
    plan = raw("kalimantan-2015-09-burned-area")
    dataset(plan, MCD64A1)["dataset_id"] = "mcd64a1-invented-copy"
    method(plan, "mcd64a1_burned_area")["inputs"][0]["dataset_id"] = "mcd64a1-invented-copy"
    assert {C.UNREGISTERED_DATASET, C.DATA_UNAVAILABLE} <= errors(plan)


def test_feasibility_claim_must_match_the_case_check() -> None:
    plan = raw("uttarakhand-2024-missing-data")
    method(plan, "mcd64a1_burned_area")["feasibility"] = "feasible"
    assert C.REGISTRY_MISMATCH in errors(plan)


def test_catalogue_method_without_registered_assets_is_infeasible() -> None:
    plan = raw("heatwave-fire-reverse-causality")
    method(plan, "bidirectional-lead-lag")["catalogue_id"] = "era5_t2m_anomaly"
    assert C.METHOD_INFEASIBLE in errors(plan)
    method(plan, "bidirectional-lead-lag")["catalogue_id"] = "no_such_method"
    assert C.METHOD_INFEASIBLE in errors(plan)


@pytest.mark.parametrize("action", [PlanAction.TRAIN_MODEL, PlanAction.DELETE_DATA])
def test_gate_refuses_training_and_deletion_even_when_requested(action: PlanAction) -> None:
    assert gate_refusal(action) is not None
    assert gate_refusal(ApprovalAction.DOWNLOAD) is None
    plan = raw("singapore-pm25-nowcast")
    plan["operations"] = [{"op_id": "op", "action": action.value}]
    assert {C.MISSING_APPROVAL, C.ACTION_NOT_SUPPORTED} <= errors(plan)
    plan["approval_scope"].append(action.value)
    plan["approval_requests"].append({"request_id": "r", "action": action.value, "reason": "x"})
    found = errors(plan)
    assert C.ACTION_NOT_SUPPORTED in found
    assert C.MISSING_APPROVAL not in found


def test_machine_learning_with_a_design_always_needs_training_approval() -> None:
    plan = raw("singapore-pm25-nowcast")
    method(plan, "lagged-ridge-nowcast")["method_class"] = "machine_learning"
    assert C.MISSING_APPROVAL in errors(plan)


def test_month_outside_pinned_data_gives_plan_level_data_unavailable() -> None:
    plan = raw("kalimantan-2015-12-outside-pinned")
    report = review(plan)
    assert report.abstentions == ("data_unavailable",)
    assert report.checks("error") == set()
    plan["abstentions"] = []
    report = review(plan)
    assert report.verdict == "revise"
    assert C.DATA_UNAVAILABLE in report.checks("error")
    assert "data_unavailable" in report.abstentions


def test_causal_question_needs_a_causation_abstention() -> None:
    plan = raw("mumbai-aqi-deforestation")
    assert "causation_not_identifiable" in review(plan).abstentions
    plan["abstentions"] = []
    assert C.CAUSAL_ABSTENTION_MISSING in errors(plan)
    plan = raw("kalimantan-2015-09-burned-area")
    report = review(plan)
    assert report.abstentions == ()
    assert C.CAUSAL_ABSTENTION_MISSING not in report.checks()


def _claim(claim_id: str, status: ObservationStatus, value: float | None) -> EvidenceClaim:
    supported = status is ObservationStatus.SUPPORTED_OBSERVATION
    return EvidenceClaim(
        claim_id=claim_id,
        case_id="c",
        method_id="m",
        variable=ScientificVariable.BURNED_AREA,
        area=StudyArea(
            area_id="a", name="a", bbox=BoundingBox(min_lon=0, min_lat=0, max_lon=1, max_lat=1)
        ),
        period=StudyPeriod(
            start=datetime(2015, 9, 1, tzinfo=UTC),
            end=datetime(2015, 10, 1, tzinfo=UTC),
            local_zone="UTC",
        ),
        value=value,
        unit="ha",
        source_sha256=("0" * 64,) if supported else (),
        valid_fraction=0.97 if supported else None,
        observation_status=status,
    )


def test_report_states_only_values_from_verified_findings() -> None:
    claims = [
        _claim("A1.1", ObservationStatus.SUPPORTED_OBSERVATION, 100.0),
        _claim("A1.2", ObservationStatus.CONTRADICTED, 50.0),
        _claim("A1.3", ObservationStatus.INSUFFICIENT_DATA, None),
        _claim("A1.4", ObservationStatus.NOT_VERIFIED, 7.0),
    ]
    assert [v.claim_id for v in reportable_values(claims)] == ["A1.1"]
    plan = raw("singapore-2015-haze")
    plan["verification_plan"]["report_values"] = "model_text"
    with pytest.raises(ValidationError, match="verified_findings_only"):
        InvestigationPlan.model_validate(plan)
