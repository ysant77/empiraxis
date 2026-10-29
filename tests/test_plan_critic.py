"""The deterministic plan critic: each science contract fires on a typed mistake and stays
quiet on a valid plan that uses the same datasets or words honestly."""

from __future__ import annotations

from typing import Any

import pytest
from plan_helpers import PLANS, dataset, errors, method, raw, registry, review

from earthlab.planning import CheckId, load_plan, plan_digest, review_plan

C = CheckId
EXPECTED_VERDICTS = {
    "singapore-2015-haze": "accept",
    "kalimantan-2015-09-burned-area": "accept",
    "kalimantan-2015-10-failed-coverage": "revise",
    "uttarakhand-2024-missing-data": "needs_evidence",
    "mumbai-aqi-deforestation": "needs_evidence",
    "heatwave-fire-reverse-causality": "needs_evidence",
    "singapore-pm25-nowcast": "accept",
    "kalimantan-2015-12-outside-pinned": "needs_evidence",
}


@pytest.mark.parametrize(("name", "verdict"), sorted(EXPECTED_VERDICTS.items()))
def test_fixture_verdicts(name: str, verdict: str) -> None:
    report = review_plan(load_plan(PLANS / f"{name}.yaml"), registry())
    assert report.verdict == verdict
    assert report.task.role_id == "scientific_critic"
    assert report.task.parent_task_id == load_plan(PLANS / f"{name}.yaml").task.task_id


def test_firms_used_as_burned_area_is_flagged() -> None:
    plan = raw("kalimantan-2015-09-burned-area")
    firms = method(plan, "mcd64a1_burned_area")["inputs"][1]
    firms.update(used_as="burned_area", role="input")
    assert C.FIRE_DETECTIONS_AS_BURNED_AREA in errors(plan)


def test_firms_count_selected_for_a_burned_area_target_is_flagged() -> None:
    plan = raw("kalimantan-2015-09-burned-area")
    plan["method_choice"].update(selected_id="firms-count", simpler_baseline_id=None, rejected=[])
    assert C.FIRE_DETECTIONS_AS_BURNED_AREA in errors(plan)


def test_firms_as_context_next_to_burned_area_is_not_flagged() -> None:
    report = review(raw("kalimantan-2015-09-burned-area"))
    assert report.findings == ()


def test_lst_used_as_air_temperature_is_flagged() -> None:
    plan = raw("heatwave-fire-reverse-causality")
    lst = method(plan, "bidirectional-lead-lag")["inputs"][2]
    lst.update(used_as="air_temperature_anomaly", role="input")
    assert C.LST_AS_AIR_TEMPERATURE in errors(plan)


def test_lst_as_lst_and_era5_as_reanalysis_are_not_flagged() -> None:
    checks = review(raw("heatwave-fire-reverse-causality")).checks()
    assert not checks & {C.LST_AS_AIR_TEMPERATURE, C.REANALYSIS_AS_FORECAST}


def test_reanalysis_described_as_operational_forecast_is_flagged() -> None:
    plan = raw("heatwave-fire-reverse-causality")
    method(plan, "bidirectional-lead-lag")["inputs"][0]["assumed_kind"] = "operational_forecast"
    assert C.REANALYSIS_AS_FORECAST in errors(plan)


def _design(plan: dict[str, Any]) -> dict[str, Any]:
    design: dict[str, Any] = plan["experiment_design"]
    return design


def test_random_split_on_hourly_series_is_an_error() -> None:
    plan = raw("singapore-pm25-nowcast")
    _design(plan)["split"] = {"method": "random_rows"}
    assert C.RANDOM_SPLIT_TIME_SERIES in errors(plan)


def test_random_split_with_embargo_is_only_a_warning() -> None:
    plan = raw("singapore-pm25-nowcast")
    control = {"embargo_hours": 48, "justification": "Two-day gap", "evidence_refs": ["acf:lag"]}
    _design(plan)["split"] = {"method": "random_rows", "leakage_control": control}
    report = review(plan)
    assert C.RANDOM_SPLIT_TIME_SERIES in report.checks("warning")
    assert report.verdict == "accept_with_warnings"


def test_random_split_over_scenes_is_not_flagged() -> None:
    plan = raw("singapore-pm25-nowcast")
    _design(plan).update(sample_unit="scene", split={"method": "random_rows"})
    assert C.RANDOM_SPLIT_TIME_SERIES not in review(plan).checks()


def test_future_observation_in_features_is_flagged() -> None:
    plan = raw("singapore-pm25-nowcast")
    _design(plan)["features"][0]["valid_offset_hours"] = 1
    assert C.FUTURE_INFORMATION_IN_FEATURES in errors(plan)


def test_reanalysis_feature_inside_its_latency_is_flagged() -> None:
    plan = raw("singapore-pm25-nowcast")
    _design(plan)["features"].append(
        {"name": "era5_wind_lag1", "dataset_id": "era5-wind-2015", "valid_offset_hours": -1}
    )
    assert C.FUTURE_INFORMATION_IN_FEATURES in errors(plan)


def test_reference_labels_as_features_are_flagged() -> None:
    plan = raw("singapore-pm25-nowcast")
    _design(plan)["features"].append(
        {"name": "label", "dataset_id": "nea-pm25-2019-holdout", "valid_offset_hours": -24}
    )
    assert C.FUTURE_INFORMATION_IN_FEATURES in errors(plan)


def test_forecast_valid_after_issue_but_issued_before_is_allowed() -> None:
    checks = review(raw("singapore-pm25-nowcast")).checks()
    assert C.FUTURE_INFORMATION_IN_FEATURES not in checks


def test_causal_intent_without_identification_is_an_error() -> None:
    plan = raw("mumbai-aqi-deforestation")
    plan["research_intent"] = "causal_inference"
    assert C.CAUSAL_FROM_WEAK_DESIGN in errors(plan)
    plan["causal_design"] = {"identification": "wind_direction_only"}
    assert C.CAUSAL_FROM_WEAK_DESIGN in errors(plan)


def test_causal_intent_with_a_design_stays_unestablished_warning() -> None:
    plan = raw("mumbai-aqi-deforestation")
    plan["research_intent"] = "causal_inference"
    plan["causal_design"] = {"identification": "controlled_comparison", "evidence_refs": ["x"]}
    assert C.CAUSAL_FROM_WEAK_DESIGN in review(plan).checks("warning")


def test_causal_words_in_the_question_do_not_trigger_the_causal_rule() -> None:
    plan = raw("mumbai-aqi-deforestation")
    assert "cause" in plan["research_question"]
    assert C.CAUSAL_FROM_WEAK_DESIGN not in review(plan).checks()


def test_pm25_estimate_from_wind_alone_is_flagged() -> None:
    plan = raw("singapore-pm25-nowcast")
    method(plan, "lagged-ridge-nowcast")["inputs"].pop(0)
    _design(plan)["features"].pop(0)
    assert C.PM25_FROM_WIND_ALONE in errors(plan)


def test_wind_only_transport_plausibility_is_not_flagged() -> None:
    plan = raw("singapore-pm25-nowcast")
    method(plan, "lagged-ridge-nowcast")["inputs"].pop(0)
    plan["research_intent"] = "transport_plausibility"
    assert C.PM25_FROM_WIND_ALONE not in review(plan).checks()


def test_failed_coverage_uses_the_measured_october_fraction() -> None:
    report = review(raw("kalimantan-2015-10-failed-coverage"))
    coverage = [f for f in report.findings if f.check is C.DATA_COVERAGE]
    assert [f.message.split(": ")[1] for f in coverage] == ["valid fraction 0.4597 is below 0.8"]
    assert coverage[0].severity == "error"
    assert len({f.finding_id for f in report.findings}) == len(report.findings)


def test_declared_gap_turns_coverage_into_uncertainty() -> None:
    plan = raw("uttarakhand-2024-missing-data")
    assert review(plan).checks("error") == set()
    plan["evidence_gaps"] = []
    assert {C.DATA_UNAVAILABLE, C.METHOD_INFEASIBLE} <= errors(plan)


def test_missing_download_and_spend_approvals_are_flagged() -> None:
    plan = raw("singapore-pm25-nowcast")
    plan["approval_requests"] = []
    assert C.MISSING_APPROVAL in errors(plan)
    plan = raw("singapore-pm25-nowcast")
    method(plan, "lagged-ridge-nowcast")["compute"] = "hosted"
    assert C.MISSING_APPROVAL in errors(plan)


def test_operation_cost_above_the_requested_cap_is_flagged() -> None:
    plan = raw("singapore-pm25-nowcast")
    op = {"op_id": "dl", "action": "download", "dataset_ids": ["gfs-wind-forecast-2015"]}
    plan["operations"] = [{**op, "estimated_bytes": 50_000_000}]
    assert C.MISSING_APPROVAL not in review(plan).checks()
    plan["operations"] = [{**op, "estimated_bytes": 500_000_000}]
    assert C.MISSING_APPROVAL in errors(plan)


def test_approval_request_outside_task_scope_is_flagged() -> None:
    plan = raw("singapore-pm25-nowcast")
    plan["approval_scope"] = []
    assert C.APPROVAL_OUTSIDE_SCOPE in errors(plan)


def test_model_without_experiment_design_is_flagged() -> None:
    plan = raw("singapore-pm25-nowcast")
    plan["experiment_design"] = None
    assert C.NO_EXPERIMENT_DESIGN in errors(plan)


def test_association_without_rival_hypothesis_warns() -> None:
    plan = raw("heatwave-fire-reverse-causality")
    plan["hypotheses"] = plan["hypotheses"][:1]
    assert C.NO_COMPETING_HYPOTHESIS in review(plan).checks("warning")


def test_report_is_deterministic_and_bound_to_the_plan_hash() -> None:
    plan = load_plan(PLANS / "kalimantan-2015-10-failed-coverage.yaml")
    first, second = review_plan(plan, registry()), review_plan(plan, registry())
    assert first == second
    assert first.plan_sha256 == plan_digest(plan)
    assert [f.priority for f in first.findings] == list(range(1, len(first.findings) + 1))
    assert all(f"sha256:{first.plan_sha256}" in f.evidence_refs for f in first.findings)


def test_useful_plans_for_unsupported_claims_carry_gaps_and_rivals() -> None:
    for name in ("mumbai-aqi-deforestation", "heatwave-fire-reverse-causality"):
        plan = load_plan(PLANS / f"{name}.yaml")
        assert plan.requested_intent == "causal_inference"
        assert plan.research_intent == "association"
        assert plan.evidence_gaps
        assert {h.direction for h in plan.hypotheses} - {"forward"}
        assert review_plan(plan, registry()).verdict == "needs_evidence"
    assert dataset(raw("mumbai-aqi-deforestation"), "cpcb-aqi-mumbai-2023")


def _scene(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [dataset(plan, "hls-l30-kalimantan-2015")]


def _segmentation_plan(**scene: Any) -> dict[str, Any]:
    plan = raw("kalimantan-2015-09-burned-area")
    base = dataset(plan, "mcd64a1-061-kalimantan-2015")
    hls = {
        **base,
        "dataset_id": "hls-l30-kalimantan-2015",
        "product": "HLS L30",
        "availability": "registered_not_downloaded",
        "sha256": None,
        "product_kind": "satellite_retrieval",
        "quantity": "surface_reflectance",
        "native_variables": ["B02", "B03", "B04", "B05", "B06", "B07", "Fmask"],
        "bands": ["B02", "B03", "B04", "B05", "B06", "B07"],
        "normalization": "hls-v2-scale",
        "quality_mask": "Fmask",
    }
    plan["data_candidates"].append({**hls, **scene})
    plan["method_candidates"].append(
        {
            "method_id": "burn-scar-segmentation",
            "method_class": "machine_learning",
            "technique": "image_segmentation",
            "inputs": [
                {
                    "dataset_id": "hls-l30-kalimantan-2015",
                    "used_as": "surface_reflectance",
                    "assumed_kind": "satellite_retrieval",
                }
            ],
            "feasibility": "not_implemented",
            "runtime_estimate_s": 900,
            "image_requirements": {
                "bands": ["B02", "B03", "B04", "B05", "B06", "B07"],
                "normalization": "hls-v2-scale",
            },
        }
    )
    plan["method_choice"].update(selected_id="burn-scar-segmentation", rejected=[])
    return plan


def test_segmentation_with_compatible_scenes_is_not_flagged() -> None:
    plan = _segmentation_plan()
    assert C.INCOMPATIBLE_IMAGE_INPUT not in review(plan, _scene(plan)).checks()


@pytest.mark.parametrize(
    "scene",
    [
        {"bands": ["B02", "B03", "B04"]},
        {"normalization": "raw-dn"},
        {"quality_mask": None},
    ],
)
def test_segmentation_with_incompatible_scenes_is_flagged(scene: dict[str, Any]) -> None:
    plan = _segmentation_plan(**scene)
    assert C.INCOMPATIBLE_IMAGE_INPUT in errors(plan, _scene(plan))
