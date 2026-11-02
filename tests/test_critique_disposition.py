"""The Lead must answer a critique, and code decides whether the answer holds."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fake_client import ScriptedClient, call
from pydantic import ValidationError
from test_method_review import CASE, CONCERN, FACTS, HYBRID, PLAN, SOURCE, proposal, seats

from earthlab.harness.claims import ladder
from earthlab.harness.contracts import (
    DecisionRecordV1,
    EvaluationReportV1,
    ModelScore,
    ResearchRequestV1,
)
from earthlab.harness.engine import run_harness
from earthlab.harness.method_review import (
    CritiqueV1,
    DispositionV1,
    ReviewCode,
    apply_claims,
    check_proposal,
    check_recommendation,
    disposition_issues,
    run_review,
)
from earthlab.harness.regression import PM25_PROBLEM, RegressionAdapter
from earthlab.harness.seats import Seats
from earthlab.llm.providers import ProviderConfig

THIN = {**CASE, "candidates": CASE["candidates"][:1]}
RESPONSE = "The added method removes the concern and keeps the same baseline."
ACCEPT: dict[str, Any] = {"disposition": "accepted", "response": RESPONSE, "revised_case": CASE}
REBUT: dict[str, Any] = {
    "disposition": "rebutted", "evidence_fields": ["usable_rows"],
    "response": "The evaluator reports mae for elevated hours, and the rows cover those hours.",
}  # fmt: skip
OPEN: dict[str, Any] = {
    "disposition": "needs_revision",
    "response": "No measured fact answers this concern before the experiment runs.",
}
GRU_CASE = {
    **CASE, "proposed_method": "gru",
    "candidates": [{"method": "gru", "suitability": "Fits hourly sequences."},
                   {"method": "tcn", "suitability": "Fits hourly sequences."}],
}  # fmt: skip


def critique() -> CritiqueV1:
    return CritiqueV1.model_validate(CONCERN)


def answer(**fields: Any) -> DispositionV1:
    return DispositionV1.model_validate(fields)


def codes(**change: Any) -> set[ReviewCode]:
    return {f.code for f in check_proposal(proposal(**change), FACTS)}


@pytest.mark.parametrize(
    "fields",
    [
        {"disposition": "accepted", "response": RESPONSE},
        {"disposition": "rebutted", "response": RESPONSE},
        {**OPEN, "evidence_fields": ["usable_rows"]},
        {**OPEN, "revised_case": CASE},
    ],
)
def test_each_answer_carries_only_its_own_evidence(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        answer(**fields)


def test_the_record_has_no_score_or_approval_field() -> None:
    assert not {"score", "status", "approved", "waiver"} & set(DispositionV1.model_fields)


def test_an_accepted_critique_must_remove_the_finding() -> None:
    assert disposition_issues(answer(**ACCEPT), critique(), FACTS) == []
    kept = disposition_issues(answer(**{**ACCEPT, "revised_case": THIN}), critique(), FACTS)
    assert kept == ["revised_case: no_real_alternative is still there"]


def test_an_accepted_critique_cannot_move_to_a_refused_method() -> None:
    bad = {**CASE, "proposed_method": "transformer"}
    found = disposition_issues(answer(**{**ACCEPT, "revised_case": bad}), critique(), FACTS)
    assert "revised_case: unknown_method" in found


def test_an_accepted_competing_experiment_must_name_the_method() -> None:
    rival = critique().model_copy(
        update={"kind": "competing_experiment", "competing_method": "trees"}
    )
    assert disposition_issues(answer(**ACCEPT), rival, FACTS) == ["revised_case: run or name trees"]


def test_a_rebuttal_needs_a_measured_fact_and_the_critic_metric() -> None:
    assert disposition_issues(answer(**REBUT), critique(), FACTS) == []
    invented = {**REBUT, "evidence_fields": ["my_intuition"]}
    assert disposition_issues(answer(**invented), critique(), FACTS) == [
        "evidence_fields: my_intuition is not a measured fact"
    ]
    silent = {**REBUT, "response": "The rows cover those hours, so this does not apply here."}
    assert disposition_issues(answer(**silent), critique(), FACTS) == [
        "response: address mae, the critic's metric"
    ]


def test_a_rebuttal_cannot_state_a_number_nothing_measured() -> None:
    bad = {**REBUT, "response": "The mae will fall to 12.75 in elevated hours in this data."}
    assert disposition_issues(answer(**bad), critique(), FACTS) == [
        "12.75 is not in the evaluator's results"
    ]


@pytest.mark.parametrize(
    ("reply", "verdict"), [(ACCEPT, "proceed"), (REBUT, "proceed"), (OPEN, "needs_revision")]
)
def test_one_critique_and_one_response(tmp_path: Path, reply: dict[str, Any], verdict: str) -> None:
    steps = [call("propose_method", **THIN), call("submit_critique", **CONCERN),
             call("answer_critique", **reply)]  # fmt: skip
    held, client = seats(tmp_path, steps)
    done = run_review(held, FACTS)
    assert done.verdict == verdict and done.critic_calls == done.lead_responses == 1
    assert len(client.requests) == 3


def test_an_unusable_answer_leaves_the_concern_open(tmp_path: Path) -> None:
    empty = {**REBUT, "evidence_fields": ["my_intuition"]}
    steps = [call("propose_method", **THIN), call("submit_critique", **CONCERN),
             *[call("answer_critique", **empty)] * 3]  # fmt: skip
    held, client = seats(tmp_path, steps)
    done = run_review(held, FACTS)
    assert done.verdict == "needs_revision" and done.disposition is None
    assert len(client.requests) == 4  # one answer and its one correction, no debate


def test_a_review_with_no_finding_calls_nobody(tmp_path: Path) -> None:
    held, client = seats(tmp_path, [call("propose_method", **CASE)])
    done = run_review(held, FACTS)
    assert done.lead_responses == 0 and done.critic_source == "not_used"
    assert len(client.requests) == 1


def test_a_critic_on_the_same_model_is_labelled_a_second_pass(tmp_path: Path) -> None:
    steps = [call("propose_method", **THIN), call("submit_critique", **CONCERN),
             call("answer_critique", **OPEN)]  # fmt: skip
    held, _ = seats(tmp_path, steps)
    assert run_review(held, FACTS).critic_source == "same_model_second_pass"


def test_a_critic_on_another_model_is_labelled_independent(tmp_path: Path) -> None:
    lead = ScriptedClient([call("propose_method", **THIN), call("answer_critique", **OPEN)])
    other = ProviderConfig.model_validate({**lead.config.model_dump(), "model": "another"})
    critic = ScriptedClient([call("submit_critique", **CONCERN)], other)
    held = Seats("single", tmp_path, lead, {}, {"method_critic": critic})
    assert run_review(held, FACTS).critic_source == "independent_model"


def test_a_neural_case_owes_a_simple_comparison() -> None:
    assert ReviewCode.NO_SIMPLE_COMPARISON in codes(**GRU_CASE)
    named = {**GRU_CASE, "candidates": [*GRU_CASE["candidates"], CASE["candidates"][0]]}
    plan = PLAN.model_copy(update={"methods": ("persistence", "ridge", "gru")})
    facts = replace(FACTS, plan=plan)
    found = {f.code for f in check_proposal(proposal(**named), facts)}
    assert ReviewCode.NO_SIMPLE_COMPARISON not in found


def test_a_simple_case_owes_no_neural_checks() -> None:
    found = codes()
    assert not {ReviewCode.NO_SIMPLE_COMPARISON, ReviewCode.ELEVATED_NOT_TESTED} & found


def test_a_neural_regression_must_test_elevated_hours() -> None:
    assert ReviewCode.ELEVATED_NOT_TESTED in codes(**GRU_CASE)
    named = {**GRU_CASE, "failure_conditions": ["MAE above 55 ug/m3 exceeds persistence."]}
    assert ReviewCode.ELEVATED_NOT_TESTED not in codes(**named)


def test_reanalysis_cannot_stand_as_issue_time_evidence() -> None:
    assert ReviewCode.HINDSIGHT_AS_FORECAST in codes(
        data_sufficiency="ERA5 wind at the valid hour supports this issue-time forecast."
    )


def test_naming_the_hindsight_risk_is_not_using_it() -> None:
    risks = ["ERA5 is hindsight, so no feature reads it.", "The latency holds for every lag."]
    assert ReviewCode.HINDSIGHT_AS_FORECAST not in codes(leakage_risks=risks)


def decision(outcome: str, selected: str, limits: tuple[str, ...] = ()) -> DecisionRecordV1:
    return DecisionRecordV1.model_validate({
        "outcome": outcome, "selected": selected, "rejected": [], "reason": "Test.",
        "limitations": limits,
    })  # fmt: skip


def test_a_hybrid_that_loses_to_persistence_cannot_be_adopted() -> None:
    claims = ladder(HYBRID, "frozen_gru_logistic")
    out, held = apply_claims(decision("adopt", "frozen_gru_logistic"), claims)
    assert ReviewCode.ADOPT_WITHOUT_GAIN in {f.code for f in held}
    assert any("subgroup_failure" in text for text in out.limitations)


def test_retaining_the_baseline_raises_nothing() -> None:
    claims = ladder(HYBRID, "persistence_alarm")
    assert check_recommendation(decision("retain_baseline", "persistence_alarm"), claims) == []


def run(tmp_path: Path, steps: list[Any]) -> dict[str, Any]:
    request = ResearchRequestV1(request_id="r-1", objective="Assess PM2.5 at T+6 h.")
    return run_harness(
        "single", request, PM25_PROBLEM, RegressionAdapter(tmp_path, SOURCE), tmp_path,
        ScriptedClient(steps), method_review=True,
    )  # fmt: skip


STRATEGY = call("choose_strategy", strategy="statistical", reason="Enough rows for a linear fit.")
FINISH = call("review_results", action="finish", reason="No reason to change the method.")
ABSTAIN = call("recommend", outcome="abstain", reason="Nothing to adopt in this test.")


def test_an_open_concern_stops_the_run_before_any_work(tmp_path: Path) -> None:
    critic = {**CONCERN, "test": {**CONCERN["test"], "metric": "mae"}}
    steps = [STRATEGY, call("propose_method", **THIN), call("submit_critique", **critic),
             call("answer_critique", **OPEN)]  # fmt: skip
    out = run(tmp_path, steps)
    assert out["status"] == "needs_revision" and "plan-1" not in out["artifacts"]
    assert out["method_review"]["disposition"]["disposition"] == "needs_revision"
    events = [json.loads(line)["event"] for line in (tmp_path / "trace.jsonl").open()]
    assert "tool_result" not in events


def test_an_answered_critique_lets_the_run_continue(tmp_path: Path) -> None:
    steps = [STRATEGY, call("propose_method", **THIN), call("submit_critique", **CONCERN),
             call("answer_critique", **ACCEPT), FINISH, ABSTAIN]  # fmt: skip
    out = run(tmp_path, steps)
    assert out["status"] == "awaiting_human" and out["method_review"]["verdict"] == "proceed"
    assert out["code_outcome"] == "retain_baseline"


def test_no_score_to_compare_does_not_stop_a_raster_adoption() -> None:
    row = ModelScore(model="raster_deterministic", metrics={}, passes=True)
    raster = HYBRID.model_copy(update={"scores": (row,), "reference": "raster_deterministic"})
    claims = ladder(raster, "raster_deterministic")
    assert claims.better_than_baseline.state == "not_tested"
    assert check_recommendation(decision("adopt_limited", "raster_deterministic"), claims) == []


def test_the_critic_is_told_the_method_names_it_may_use(tmp_path: Path) -> None:
    steps = [call("propose_method", **THIN), call("submit_critique", **CONCERN),
             call("answer_critique", **OPEN)]  # fmt: skip
    held, client = seats(tmp_path, steps)
    run_review(held, FACTS)
    sent = client.requests[1]["messages"][1]["content"]
    assert '"eligible_methods"' in sent and '"ridge"' in sent and '"gru"' in sent


def test_a_subgroup_failure_joins_the_limits_with_the_review_off(tmp_path: Path) -> None:
    class Open(RegressionAdapter):
        def allowed(self, report: EvaluationReportV1) -> dict[str, list[str]]:
            return {"adopt": ["B4_lagged_ridge"]}

    steps = [STRATEGY, FINISH, call(
        "recommend", outcome="adopt", model_id="B4_lagged_ridge", reason="Test of the limits."
    )]  # fmt: skip
    done = run_harness(
        "single", ResearchRequestV1(request_id="r-1", objective="Assess PM2.5 at T+6 h."),
        PM25_PROBLEM, Open(tmp_path, SOURCE), tmp_path, ScriptedClient(steps),
    )  # fmt: skip
    assert done["status"] == "awaiting_human"
    assert any("subgroup_failure" in text for text in done["limitations"])
