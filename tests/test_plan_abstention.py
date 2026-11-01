"""A reviewed causal abstention binds the run: the live WD-03 failure ended as verified."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say
from test_plan_step import CASE, MCD, PLAN, proposal

from earthlab.agent.limitations import ReasonCode
from earthlab.agent.loop import RunStatus
from earthlab.agent.plan_step import PlanStep
from earthlab.cases.methods import CATALOGUE
from earthlab.planning.registry import load_registry
from earthlab.runtime import Workspace, investigate, open_workspace
from earthlab.safety.scope import answer_out_of_scope
from earthlab.trace import RunTrace
from earthlab.verify.answer_audit import audit_answer

ROOT = Path(__file__).resolve().parents[1]
QUESTION = "Did plantation clearing cause the burned area in Kalimantan in September 2015?"
ABSTENTION = {
    "reason": "causation_not_identifiable",
    "note": "Burned area alone cannot identify a cause.",
    "dataset_ids": [MCD],
}


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def causal_plan() -> dict[str, Any]:
    return proposal(requested_intent="causal_inference", abstentions=[ABSTENTION])


def test_a_causal_run_that_never_declares_still_abstains(
    workspace: Workspace, tmp_path: Path
) -> None:
    claim = {
        "case_id": CASE,
        "month": "2015-09",
        "quantity": "burned_area_ha",
        "value": 77426.0,
        "statement": "Mapped burned area for the month.",
    }
    client = ScriptedClient(
        [
            call("submit_plan", **causal_plan()),
            call("burned_area_summary", case_id=CASE, month="2015-09"),
            call("submit_area_findings", claims=[claim]),
            say("Mapped burned area is in A1.1. Observations cannot show what started the fires."),
        ]
    )
    result = investigate(QUESTION, client, workspace, tmp_path, options=PLAN)
    assert result.status is RunStatus.ABSTAINED
    assert ReasonCode.CAUSATION_NOT_IDENTIFIABLE in result.limitations[0].reasons
    trace = RunTrace(tmp_path / "trace.jsonl")
    assert [e for e in trace.records() if e["event"] == "abstention_enforced"]
    trace.verify()


def test_a_declared_abstention_is_not_recorded_twice(workspace: Workspace, tmp_path: Path) -> None:
    reasons = ["causation_not_identifiable"]
    client = ScriptedClient(
        [
            call("submit_plan", **causal_plan()),
            call("declare_limitation", reasons=reasons, explanation="Observations cannot show it."),
            say("The cause cannot be identified from these observations."),
        ]
    )
    result = investigate(QUESTION, client, workspace, tmp_path, options=PLAN)
    assert result.status is RunStatus.ABSTAINED and len(result.limitations) == 1
    assert not [
        e
        for e in RunTrace(tmp_path / "trace.jsonl").records()
        if e["event"] == "abstention_enforced"
    ]


def test_the_plan_reply_says_to_abstain_now(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            call("submit_plan", **causal_plan()),
            call("declare_limitation", reasons=["causation_not_identifiable"], explanation="None."),
            say("The cause cannot be identified."),
        ]
    )
    investigate(QUESTION, client, workspace, tmp_path, options=PLAN)
    assert "declare_limitation now" in str(client.requests[1])


def test_the_plan_tool_lists_every_catalogue_method(workspace: Workspace, tmp_path: Path) -> None:
    assert workspace.cases is not None
    step = PlanStep(
        cases=workspace.cases,
        registry=load_registry(ROOT),
        approvals=[],
        trace=RunTrace(tmp_path / "trace.jsonl"),
        task_id="t1",
    )
    assert all(method in step.spec().description for method in CATALOGUE)


def test_stating_the_abstention_is_not_a_causal_claim() -> None:
    text = "The plan includes an abstention because causation is not identifiable."
    assert answer_out_of_scope(text) is None
    assert answer_out_of_scope("The burn scar exists because peat fires spread.") is not None


def test_no_missing_hours_needs_a_quality_finding() -> None:
    text = "Coverage showed complete hourly observations, with no missing hours."
    assert not audit_answer(text, {}).passed
    assert not audit_answer("There were no gaps in the record.", {}).passed
    assert audit_answer(text, {}, quality_bound=True).passed
