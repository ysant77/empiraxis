"""The pilot on the registered toy cases: the rule, the leakage limits, the human gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from earthlab.method.contracts import EvaluationPlan, HumanMethodApproval, canonical_digest
from earthlab.method.evaluate import (
    FORECASTERS,
    EvaluationUndefined,
    chronological_split,
    fit_ar1,
    measure,
)
from earthlab.method.policy import method_gate, run_pilot, verify_decision
from earthlab.method.toy import ToySeriesV1, series_digest, synthetic_series

FIXTURE = Path(__file__).parent / "fixtures" / "method" / "toy_cases_v1.json"
CASES: dict[str, dict[str, Any]] = {c["name"]: c for c in json.loads(FIXTURE.read_text())["cases"]}


def _case(name: str) -> tuple[dict[str, Any], ToySeriesV1, str]:
    case = CASES[name]
    series = ToySeriesV1.model_validate(case["series"])
    return case["proposal"], series, case["registered_plan_sha256"]


def _registered(proposal: dict[str, Any], series: ToySeriesV1, **plan: Any) -> tuple[Any, str]:
    """A proposal whose plan is registered for this series, for a data-side test."""
    changed = proposal["plan"] | {"dataset_sha256": series_digest(series)} | plan
    return proposal | {"plan": changed}, canonical_digest(EvaluationPlan(**changed))


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_fixture_is_what_the_generator_gives(name: str) -> None:
    generator = CASES[name]["generator"]
    again = synthetic_series(CASES[name]["series"]["dataset_id"], **generator)
    assert again == ToySeriesV1.model_validate(CASES[name]["series"])


def test_a_mean_reverting_series_clears_the_threshold() -> None:
    decision = run_pilot(*_case("mean_reverting"))
    assert decision.outcome == "select_candidate"
    assert decision.selected_id == "ar1_ols"
    assert decision.reason_code == "gain_cleared_threshold"
    assert decision.comparison is not None
    assert decision.comparison.relative_gain >= 0.10
    assert decision.comparison.ci_low > 0


def test_a_random_walk_keeps_the_simpler_method() -> None:
    decision = run_pilot(*_case("random_walk"))
    assert decision.outcome == "keep_baseline"
    assert decision.selected_id == "last_value"
    assert decision.reason_code == "gain_below_threshold"


def test_a_stricter_threshold_keeps_the_simpler_method_on_the_same_data() -> None:
    proposal, series, _ = _case("mean_reverting")
    strict, digest = _registered(proposal, series, min_relative_gain=0.9)
    decision = run_pilot(strict, series, digest)
    assert decision.outcome == "keep_baseline"
    assert decision.reason_code == "gain_below_threshold"


def test_a_gain_with_an_interval_that_reaches_zero_is_not_stable() -> None:
    proposal = _case("mean_reverting")[0]
    series = synthetic_series("synthetic-noisy", seed=42, phi=0.85, length=120)
    plan, digest = _registered(proposal, series, min_relative_gain=0.05)
    decision = run_pilot(plan, series, digest)
    assert decision.comparison is not None
    assert decision.comparison.ci_low <= 0
    assert decision.comparison.relative_gain >= 0.05
    assert decision.reason_code == "gain_not_stable"
    assert decision.selected_id == "last_value"


def test_a_decision_records_what_it_did_not_evaluate() -> None:
    decision = run_pilot(*_case("mean_reverting"))
    assert any("gradient_boosting" in risk for risk in decision.unresolved_risks)
    assert [c.candidate_id for c in decision.candidates][-1] == "gradient_boosting"
    assert decision.human_approval.required is True


def test_a_run_is_reproducible() -> None:
    assert run_pilot(*_case("mean_reverting")) == run_pilot(*_case("mean_reverting"))


def test_the_split_is_chronological_with_a_gap() -> None:
    plan = EvaluationPlan.model_validate(CASES["mean_reverting"]["proposal"]["plan"])
    split = chronological_split(240, plan)
    assert split == (144, 147)
    decision = run_pilot(*_case("mean_reverting"))
    assert decision.comparison is not None
    assert decision.comparison.test_samples == 240 - 147
    assert decision.comparison.train_pairs == 143


def test_future_values_cannot_change_the_fit() -> None:
    _, series, _ = _case("mean_reverting")
    plan = EvaluationPlan.model_validate(CASES["mean_reverting"]["proposal"]["plan"])
    train_end = chronological_split(len(series.values), plan).train_end
    changed = (*series.values[:train_end], *(v + 500.0 for v in series.values[train_end:]))
    original_fit = fit_ar1(series.values[:train_end])
    changed_fit = fit_ar1(changed[:train_end])
    assert original_fit(41.0) == changed_fit(41.0)


def test_a_series_that_is_too_short_abstains() -> None:
    proposal = _case("mean_reverting")[0]
    series = synthetic_series("synthetic-short", seed=1, phi=0.3, length=40)
    plan, digest = _registered(proposal, series)
    decision = run_pilot(plan, series, digest)
    assert decision.outcome == "abstain"
    assert decision.reason_code == "data_unsuitable"
    assert decision.comparison is None
    assert {c.check_id for c in decision.suitability if not c.passed} == {
        "train_pairs",
        "test_samples",
    }


@pytest.mark.parametrize(
    ("change", "failed"),
    [
        ({"values": (*[1.0] * 120, float("nan"), *[1.0] * 119)}, "finite_values"),
        ({"steps": (5, *range(1, 240))}, "ordered_steps"),
        ({"steps": (0, 1)}, "equal_lengths"),
        ({"values": (7.0,) * 240}, "train_varies"),
    ],
)
def test_unsuitable_data_abstain_before_any_measurement(
    change: dict[str, Any], failed: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: object) -> None:
        raise AssertionError("measured unsuitable data")

    monkeypatch.setattr("earthlab.method.policy.measure", refuse)
    proposal, series, _ = _case("mean_reverting")
    bad = series.model_copy(update=change)
    plan, digest = _registered(proposal, bad)
    decision = run_pilot(plan, bad, digest)
    assert decision.reason_code == "data_unsuitable"
    assert failed in decision.reason


def test_a_zero_baseline_error_abstains() -> None:
    proposal = _case("mean_reverting")[0]
    flat = tuple([*range(144), *[144.0] * 96])
    series = ToySeriesV1(dataset_id="synthetic-flat", steps=tuple(range(240)), values=flat)
    plan, digest = _registered(proposal, series)
    decision = run_pilot(plan, series, digest)
    assert decision.outcome == "abstain"
    assert decision.reason_code == "evaluation_undefined"


def test_measure_refuses_a_series_with_no_variation() -> None:
    plan = EvaluationPlan.model_validate(CASES["mean_reverting"]["proposal"]["plan"])
    series = ToySeriesV1(dataset_id="synthetic-flat", steps=tuple(range(240)), values=(3.0,) * 240)
    with pytest.raises(EvaluationUndefined):
        measure(series, plan, "last_value", "ar1_ols")


def test_the_allowlist_holds_one_baseline_and_one_challenger() -> None:
    assert {kind for kind, _ in FORECASTERS.values()} == {"deterministic", "statistical"}


def _approval(
    decision_digest: str, *, answer: str = "approve", task: str = "toy-mean-reverting"
) -> HumanMethodApproval:
    return HumanMethodApproval.model_validate(
        {
            "task_id": task,
            "decision_sha256": decision_digest,
            "decision": answer,
            "approver": "owner",
        }
    )


def test_a_decision_needs_a_person_for_this_exact_record() -> None:
    proposal, series, digest = _case("mean_reverting")
    decision = run_pilot(proposal, series, digest)
    assert verify_decision(decision, series) == ()
    assert method_gate(decision, series, None).stage == "human"
    wrong = _approval("b" * 64)
    assert method_gate(decision, series, wrong).allowed is False
    exact = canonical_digest(decision)
    rejected = method_gate(decision, series, _approval(exact, answer="reject"))
    assert (rejected.allowed, rejected.reasons) == (False, ("rejected by human review",))
    assert method_gate(decision, series, _approval(exact)).allowed is True


def test_an_abstention_cannot_pass_the_gate_even_with_an_approval() -> None:
    proposal, series, _ = _case("mean_reverting")
    decision = run_pilot(proposal, series, "c" * 64)
    assert decision.outcome == "abstain"
    approval = _approval(canonical_digest(decision))
    gate = method_gate(decision, series, approval)
    assert (gate.allowed, gate.stage) == (False, "decision")
    assert verify_decision(decision, series) != ()
