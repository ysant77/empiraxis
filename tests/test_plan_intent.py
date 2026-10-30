"""The runtime decides whether a question asks for a cause; the model's plan label cannot
turn a causal question into a non-causal one (the SB-04 failure in the plan-review bench)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from plan_helpers import registry as shared_registry

from earthlab.agent.plan_step import PlanStep
from earthlab.bench.scenarios import load_scenarios
from earthlab.planning.intent import asks_for_cause, enforce_requested_intent
from earthlab.planning.proposal import PlanProposal, build_plan
from earthlab.planning.registry import load_registry
from earthlab.planning.vocab import ResearchIntent
from earthlab.runtime import Workspace, open_workspace
from earthlab.trace import RunTrace

ROOT = Path(__file__).resolve().parents[1]
CASE = "kalimantan-2015-burned-area"
MCD = "mcd64a1-061-kalimantan-2015"
CAUSAL_QUESTION = "Did the September fires in the study area cause the haze in Singapore?"


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def proposal(**overrides: Any) -> PlanProposal:
    base: dict[str, Any] = {
        "case_id": CASE,
        "requested_intent": "observational_summary",
        "research_intent": "observational_summary",
        "target": "burned_area",
        "period_start": "2015-09-01T00:00:00Z",
        "period_end": "2015-10-01T00:00:00Z",
        "datasets": [{"dataset_id": MCD, "used_as": "burned_area"}],
        "method_id": "mcd64a1_burned_area",
        "rationale": "MCD64A1 maps burned area.",
    }
    return PlanProposal.model_validate({**base, **overrides})


@pytest.mark.parametrize(
    "question",
    [
        CAUSAL_QUESTION,
        "Which province's fires were responsible for the haze?",
        "Can the PM2.5 peak be attributed to one fire?",
        "Was the October rise due to the fires upwind?",
        "Is the haze because of peat fires?",
        "Did the fires lead to the high readings?",
    ],
)
def test_causal_wording_is_found(question: str) -> None:
    assert asks_for_cause(question)


@pytest.mark.parametrize(
    "question",
    [
        "What was the highest hourly PM2.5 in the west region in October 2015?",
        "How many hectares burned in the study area in September 2015?",
        "How many hours were missing in the north region?",
        "Was the wind consistent with transport from the fire box?",
    ],
)
def test_non_causal_questions_are_left_alone(question: str) -> None:
    assert not asks_for_cause(question)


def test_dev_questions_flagged_are_exactly_the_causal_ones() -> None:
    """Every dev question that expects or describes a causal abstention is found, and no
    other dev question is."""
    scenarios = load_scenarios(ROOT / "evals" / "sciencebench_dev_v1.yaml")
    flagged = {s.id for s in scenarios if asks_for_cause(s.question)}
    assert flagged == {"SB-04", "SB-05d", "SB-15"}


def _plan(workspace: Workspace, question: str, intent: str) -> Any:
    assert workspace.cases is not None
    return build_plan(
        proposal(requested_intent=intent),
        workspace.cases,
        load_registry(ROOT),
        question=question,
        task_id="t1",
        revision=1,
    )


def test_a_mislabelled_causal_plan_is_corrected(workspace: Workspace) -> None:
    plan, replaced = enforce_requested_intent(
        _plan(workspace, CAUSAL_QUESTION, "observational_summary"), CAUSAL_QUESTION
    )
    assert replaced == ResearchIntent.OBSERVATIONAL_SUMMARY
    assert plan.requested_intent == ResearchIntent.CAUSAL_INFERENCE


def test_the_check_never_removes_a_causal_label(workspace: Workspace) -> None:
    question = "How many hectares burned in September 2015?"
    plan, replaced = enforce_requested_intent(
        _plan(workspace, question, "causal_inference"), question
    )
    assert replaced is None and plan.requested_intent == ResearchIntent.CAUSAL_INFERENCE


def test_plan_step_requires_the_abstention_after_the_correction(
    workspace: Workspace, tmp_path: Path
) -> None:
    assert workspace.cases is not None
    trace = RunTrace(tmp_path / "trace.jsonl")
    step = PlanStep(
        cases=workspace.cases,
        registry=shared_registry(),
        approvals=[],
        trace=trace,
        task_id="t1",
        question=CAUSAL_QUESTION,
    )
    reply = step.handle(proposal())
    assert "causal_inference" in reply["requested_intent"]
    assert reply["verdict"] == "revise"
    assert "causation_not_identifiable" in reply["suggested_reason_codes"]
    submitted = next(e for e in trace.records() if e["event"] == "plan_submitted")
    assert submitted["data"]["requested_intent_replaced"] == "observational_summary"
    trace.verify()
