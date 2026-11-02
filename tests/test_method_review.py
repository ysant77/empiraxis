"""The method review before execution, and the six claims after it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_client import ScriptedClient, call

from earthlab.cli import main
from earthlab.harness.claims import RULES, CostEvidence, ladder
from earthlab.harness.classify import EXCEED_PROBLEM, ClassificationAdapter
from earthlab.harness.contracts import (
    BudgetV1,
    DatasetProfileV1,
    EvaluationReportV1,
    ExpectedBenefit,
    ExperimentPlanV1,
    MethodProposalV1,
    ModelScore,
    ResearchRequestV1,
    SourceRef,
)
from earthlab.harness.engine import run_harness
from earthlab.harness.method_review import (
    CritiqueV1,
    ReviewCode,
    ReviewFacts,
    check_proposal,
    completeness,
    critique_issues,
    repeats_plan,
    run_review,
)
from earthlab.harness.regression import PM25_PROBLEM, RegressionAdapter
from earthlab.harness.seats import Seats
from earthlab.harness.strategy import assess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "nea" / "Historical1hrPM2.5.csv"
CASE: dict[str, Any] = {
    "hypothesis": "A lagged ridge lowers the T+6 h MAE against persistence in all regions.",
    "proposed_method": "ridge", "simplest_baseline": "persistence",
    "candidates": [{"method": "ridge", "suitability": "Fits lagged tabular rows."},
                   {"method": "climatology", "suitability": "Fits calendar means alone."}],
    "data_sufficiency": "The train years hold enough hourly rows for a linear fit.",
    "expected_benefit": {"metric": "mae", "minimum_gain": 0.2,
                         "reason": "A smaller gain does not repay the extra pipeline."},
    "leakage_risks": ["The two hour availability latency must hold for every lag."],
    "compute_seconds": 30.0,
    "failure_conditions": ["The lower limit of MAE skill is at or below zero."],
}  # fmt: skip
PROFILE = DatasetProfileV1(
    sources=(SourceRef(name="nea.csv", sha256="a" * 64),), variable="pm25", unit="ug/m3",
    usable_rows=20_000, missing_fraction=0.01, labels_present=True, granularity="1 h",
    availability_latency_hours=2,
)  # fmt: skip
PLAN = ExperimentPlanV1(
    plan_id="plan-1", methods=("persistence", "climatology", "ridge"), config={"lags": 12},
    split_protocol="validation only", metrics=("mae", "skill"), input_offset_hours=3, seed=1,
    budget=BudgetV1(max_seconds=600, max_training_seconds=300, max_model_calls=10),
)  # fmt: skip
FACTS = ReviewFacts(PM25_PROBLEM, PROFILE, assess(PM25_PROBLEM, PROFILE, 1200.0), PLAN, 20.0, 300.0)
CONCERN: dict[str, Any] = {
    "kind": "falsifiable_concern", "finding": "no_real_alternative",
    "claim": "Ridge may lose to persistence in the hours with a sudden jump in PM2.5.",
    "test": {"metric": "mae", "direction": "above", "threshold": 26.3,
             "samples": "validation hours above 55 ug/m3"},
}  # fmt: skip


def proposal(**change: Any) -> MethodProposalV1:
    return MethodProposalV1.model_validate({**CASE, **change})


def codes(value: MethodProposalV1, facts: ReviewFacts = FACTS) -> set[ReviewCode]:
    return {f.code for f in check_proposal(value, facts)}


def test_a_complete_case_has_no_finding() -> None:
    assert codes(proposal()) == set()
    assert completeness(proposal()) == []


def test_a_proposal_cannot_carry_a_score_or_an_approval() -> None:
    with pytest.raises(ValueError, match="approved"):
        proposal(approved=True)
    with pytest.raises(ValueError, match="approved"):
        CritiqueV1.model_validate({**CONCERN, "approved": True})


def test_a_placeholder_field_gets_a_correction() -> None:
    assert completeness(proposal(leakage_risks=["none"])) == ["leakage_risks[0] has no content"]


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"proposed_method": "transformer"}, ReviewCode.UNKNOWN_METHOD),
        ({"proposed_method": "segmentation_pretrained"}, ReviewCode.METHOD_BLOCKED),
        ({"proposed_method": "logistic"}, ReviewCode.NOT_IN_PLAN),
        ({"compute_seconds": 900.0}, ReviewCode.OVER_BUDGET),
    ],
)
def test_a_blocking_fault_refuses_the_method(change: dict[str, Any], code: ReviewCode) -> None:
    found = [f for f in check_proposal(proposal(**change), FACTS) if f.code == code]
    assert found and all(f.blocking for f in found)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"simplest_baseline": "ridge"}, ReviewCode.BASELINE_NOT_SIMPLEST),
        ({"candidates": CASE["candidates"][:1]}, ReviewCode.NO_REAL_ALTERNATIVE),
        ({"compute_seconds": 5.0}, ReviewCode.ESTIMATE_DISAGREES),
        ({"failure_conditions": ["It does not work well."]}, ReviewCode.UNTESTABLE_FAILURE),
        ({"leakage_risks": ["Scalers must stay on train rows."]}, ReviewCode.LATENCY_NOT_NAMED),
        ({"data_sufficiency": "The train years hold 0.77 of all rows."},
         ReviewCode.UNBACKED_DATA_CLAIM),
    ],
)  # fmt: skip
def test_a_material_fault_does_not_refuse(change: dict[str, Any], code: ReviewCode) -> None:
    found = [f for f in check_proposal(proposal(**change), FACTS) if f.code == code]
    assert found and not any(f.blocking for f in found)


def test_each_named_alternative_is_checked_too() -> None:
    other = [*CASE["candidates"], {"method": "gru", "suitability": "A short recurrent net."}]
    small = PROFILE.model_copy(update={"usable_rows": 5000})
    facts = ReviewFacts(PM25_PROBLEM, small, assess(PM25_PROBLEM, small, 1200.0), PLAN, 20.0, 300.0)
    assert ReviewCode.METHOD_BLOCKED in codes(proposal(candidates=other), facts)


def test_a_refinement_that_changes_nothing_is_detected() -> None:
    assert repeats_plan(PLAN.model_copy(update={"plan_id": "plan-2"}), PLAN)
    assert not repeats_plan(PLAN.model_copy(update={"config": {"lags": 24}}), PLAN)


def concern(**change: Any) -> CritiqueV1:
    return CritiqueV1.model_validate({**CONCERN, **change})


def test_praise_and_vague_review_are_not_accepted() -> None:
    found = check_proposal(proposal(candidates=CASE["candidates"][:1]), FACTS)
    assert critique_issues(concern(), found, FACTS) == []
    praise = concern(claim="This looks good to me and the approach is sound overall, I agree.")
    assert "agreement or praise" in critique_issues(praise, found, FACTS)[0]
    wrong = concern(finding="over_budget")
    assert "findings" in critique_issues(wrong, found, FACTS)[0]
    metric = concern(test={**CONCERN["test"], "metric": "vibes"})
    assert "test.metric" in critique_issues(metric, found, FACTS)[0]
    with pytest.raises(ValueError, match="competing"):
        concern(kind="competing_experiment")
    rival = concern(kind="competing_experiment", competing_method="segmentation_pretrained")
    assert "not eligible" in critique_issues(rival, found, FACTS)[0]


def seats(tmp_path: Path, steps: list[Any]) -> tuple[Seats, ScriptedClient]:
    client = ScriptedClient(steps)
    return Seats("single", tmp_path, client, {}), client


def test_a_clean_case_makes_no_critic_call(tmp_path: Path) -> None:
    held, client = seats(tmp_path, [call("propose_method", **CASE)])
    done = run_review(held, FACTS)
    assert done.verdict == "proceed" and done.critic_calls == 0 and len(client.requests) == 1


def test_a_material_fault_starts_one_critic_call(tmp_path: Path) -> None:
    thin = {**CASE, "candidates": CASE["candidates"][:1]}
    held, client = seats(
        tmp_path, [call("propose_method", **thin), call("submit_critique", **CONCERN)]
    )
    done = run_review(held, FACTS)
    assert done.critique_state == "usable" and done.critic_calls == 1
    assert done.verdict == "needs_revision" and done.lead_responses == 1
    assert len(client.requests) == 4  # the Lead gave no answer, and got its one correction


def test_an_unusable_critique_changes_nothing_and_is_bounded(tmp_path: Path) -> None:
    thin = {**CASE, "candidates": CASE["candidates"][:1]}
    praise = {**CONCERN, "claim": "This looks good to me and the plan seems fine overall."}
    steps = [call("propose_method", **thin), *[call("submit_critique", **praise)] * 5]
    held, client = seats(tmp_path, steps)
    done = run_review(held, FACTS)
    assert done.critique_state == "unusable" and done.critique is None
    assert done.verdict == "proceed" and len(client.requests) == 3


def test_a_blocking_fault_skips_the_critic(tmp_path: Path) -> None:
    held, client = seats(tmp_path, [call("propose_method", **{**CASE, "compute_seconds": 900.0})])
    done = run_review(held, FACTS)
    assert done.verdict == "refused" and done.critic_calls == 0 and len(client.requests) == 1


def _request() -> ResearchRequestV1:
    return ResearchRequestV1(request_id="r-1", objective="Assess PM2.5 at T+6 h.")


FINISH = call("review_results", action="finish", reason="No reason to change the method.")


def test_the_review_stays_off_unless_asked(tmp_path: Path) -> None:
    steps = [
        call("choose_strategy", strategy="statistical", reason="Enough rows for a linear fit."),
        FINISH,
        call("recommend", outcome="abstain", reason="Nothing to adopt in this test."),
    ]
    out = run_harness(
        "single", _request(), PM25_PROBLEM, RegressionAdapter(tmp_path, SOURCE), tmp_path,
        ScriptedClient(steps),
    )  # fmt: skip
    assert "method_review" not in out and "claims" not in out


def test_the_controller_refuses_before_any_work(tmp_path: Path) -> None:
    steps = [
        call("choose_strategy", strategy="statistical", reason="Enough rows for a linear fit."),
        call("propose_method", **{**CASE, "proposed_method": "transformer"}),
    ]
    out = run_harness(
        "single", _request(), PM25_PROBLEM, RegressionAdapter(tmp_path, SOURCE), tmp_path,
        ScriptedClient(steps), method_review=True,
    )  # fmt: skip
    assert out["status"] == "refused" and set(out["refusal_codes"]) == {"method_review"}
    assert not list(tmp_path.glob("predictions-*"))


def test_a_reviewed_run_reports_claims_the_lead_cannot_raise(tmp_path: Path) -> None:
    steps = [
        call("choose_strategy", strategy="statistical", reason="Enough rows for a linear fit."),
        call("propose_method", **CASE), FINISH,
        call("recommend", outcome="abstain", reason="Nothing to adopt in this test."),
    ]  # fmt: skip
    out = run_harness(
        "single", _request(), PM25_PROBLEM, RegressionAdapter(tmp_path, SOURCE), tmp_path,
        ScriptedClient(steps), method_review=True,
    )  # fmt: skip
    assert out["status"] == "awaiting_human" and out["method_review"]["verdict"] == "proceed"
    assert out["claims"]["approved_for_intended_use"]["state"] == "pending_human"
    assert out["code_outcome"] == "retain_baseline"


def test_a_repeated_refinement_runs_no_second_experiment(tmp_path: Path) -> None:
    menu = {"lags": 6, "penalty": 1.0, "balanced": True, "reason": "Six lags keep it small."}
    case = {
        **CASE, "proposed_method": "logistic", "simplest_baseline": "persistence",
        "candidates": [{"method": "logistic", "suitability": "A linear classifier fits."},
                       {"method": "climatology", "suitability": "A calendar rate fits."}],
        "expected_benefit": {**CASE["expected_benefit"], "metric": "f1"},
        "failure_conditions": ["The lower limit of F1 gain is at or below zero."],
        "compute_seconds": 5.0,
    }  # fmt: skip
    steps = [
        call("choose_strategy", strategy="statistical", reason="Enough rows for a linear fit."),
        call("choose_method", **menu), call("propose_method", **case),
        call("review_results", action="refine", reason="Try the same method once more."),
        call("choose_method", **menu),
        call("recommend", outcome="abstain", reason="Nothing to adopt in this test."),
    ]  # fmt: skip
    request = ResearchRequestV1(request_id="r-2", objective="Assess a PM2.5 exceedance class.")
    out = run_harness(
        "single", request, EXCEED_PROBLEM, ClassificationAdapter(tmp_path, SOURCE), tmp_path,
        ScriptedClient(steps), method_review=True,
    )  # fmt: skip
    assert out["status"] == "awaiting_human" and "plan-2" not in out["artifacts"]


def report(rows: tuple[ModelScore, ...], classify: bool = True) -> EvaluationReportV1:
    return EvaluationReportV1(
        evaluator="earthlab.harness.eval_classify" if classify else "earthlab.forecast.evaluator",
        evaluator_sha256="a" * 64, split_scored="validation",
        reference="persistence_alarm" if classify else "B0_persistence", scores=rows,
    )  # fmt: skip


def region(*values: float) -> dict[str, dict[str, float | None]]:
    return {f"region_{i}": {"f1": v} for i, v in enumerate(values)}


HYBRID = report((
    ModelScore(model="persistence_alarm", metrics={"f1": 0.306}, passes=False,
               subgroups=region(0.3, 0.3)),
    ModelScore(model="logistic", metrics={"f1": 0.162}, passes=False, low=-0.2, high=-0.1,
               subgroups=region(0.1, 0.2)),
    ModelScore(model="frozen_gru_logistic", metrics={"f1": 0.255}, low=-0.165, high=-0.001,
               passes=False, reasons=("the lower limit is not above zero",),
               subgroups=region(0.2, 0.25)),
))  # fmt: skip


def test_the_s2_hybrid_ran_and_beat_logistic_but_adoption_is_not_justified() -> None:
    claims = ladder(HYBRID, "frozen_gru_logistic", "rejected")
    assert claims.technically_feasible.state == claims.experimentally_tested.state == "passed"
    assert claims.better_than_baseline.state == "failed"
    assert claims.better_than_baseline.basis == "exploratory"
    assert claims.robust_across_subgroups.state == "failed"
    assert claims.justified_by_incremental_cost.state == "failed"
    assert claims.approved_for_intended_use.state == "failed"


REGRESSION = report((
    ModelScore(model="B0_persistence", metrics={"mae": 5.465, "above_55_mae": 26.3}, passes=False),
    ModelScore(model="M_ridge", metrics={"mae": 4.65, "above_55_mae": 37.3}, low=0.138, high=0.158,
               passes=True),
), classify=False)  # fmt: skip
BENEFIT = ExpectedBenefit(metric="mae", minimum_gain=0.2, reason="Below this it does not pay.")


def test_a_model_can_pass_some_claims_and_fail_others() -> None:
    claims = ladder(REGRESSION, "M_ridge", "evaluated", CostEvidence(BENEFIT, 30.0, 12.0))
    assert claims.better_than_baseline.state == "passed"
    assert claims.better_than_baseline.basis == "frozen_protocol"
    assert claims.robust_across_subgroups.state == "failed"
    assert claims.robust_across_subgroups.basis == "exploratory"
    assert claims.justified_by_incremental_cost.state == "passed"
    assert claims.approved_for_intended_use.state == "pending_human"


def test_cost_needs_a_declared_case_and_must_stay_inside_it() -> None:
    assert ladder(REGRESSION, "M_ridge").justified_by_incremental_cost.state == "not_measured"
    late = ladder(REGRESSION, "M_ridge", cost=CostEvidence(BENEFIT, 30.0, 45.0))
    assert late.justified_by_incremental_cost.state == "failed"
    wanted = BENEFIT.model_copy(update={"minimum_gain": 2.0})
    small = ladder(REGRESSION, "M_ridge", cost=CostEvidence(wanted, 30.0, 12.0))
    assert small.justified_by_incremental_cost.state == "failed"
    other = BENEFIT.model_copy(update={"metric": "f1"})
    gone = ladder(REGRESSION, "M_ridge", cost=CostEvidence(other, 30.0, 12.0))
    assert gone.justified_by_incremental_cost.state == "not_measured"


def test_only_a_signed_status_approves_and_a_missing_row_claims_nothing() -> None:
    assert ladder(REGRESSION, "M_ridge", "approved").approved_for_intended_use.state == "passed"
    done = ladder(HYBRID, "frozen_gru_logistic", "rejected", human_decided=True)
    assert "human" in done.approved_for_intended_use.evidence
    empty = ladder(REGRESSION, "M_lost")
    assert empty.technically_feasible.state == "not_tested"
    assert empty.better_than_baseline.state == "not_tested"


def test_a_rule_set_after_the_e1_results_stays_exploratory() -> None:
    late = {k for k, r in RULES.items() if r.established == "after_e1_results"}
    assert late == {"elevated_hours_limit", "classification_f1_gain", "region_f1_robustness"}


def test_the_claims_command_reads_a_saved_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "report.json"
    path.write_text(REGRESSION.model_dump_json(), encoding="utf-8")
    args = ["method-claims", "--report", str(path), "--model", "M_ridge"]
    assert main(args) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["better_than_baseline"]["state"] == "passed"
