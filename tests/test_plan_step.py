"""The plan step in the agent loop: plan first, one revision, approval gate, trace events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say
from plan_helpers import registry as shared_registry

from earthlab.acquire.gate import load_approvals
from earthlab.agent.loop import RunStatus
from earthlab.agent.plan_step import PlanStep
from earthlab.agent.prompts import PLAN_FIRST, system_prompt
from earthlab.events.adapter import load_run
from earthlab.planning.proposal import PlanProposal, build_plan
from earthlab.planning.registry import load_registry
from earthlab.runtime import RunOptions, Workspace, investigate, open_workspace
from earthlab.trace import RunTrace

PLAN = RunOptions(plan_review=True)

ROOT = Path(__file__).resolve().parents[1]
CASE = "kalimantan-2015-burned-area"
MCD = "mcd64a1-061-kalimantan-2015"
FIRMS = "firms-modis-sp-kalimantan-2015"


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def proposal(month: str = "09", **overrides: Any) -> dict[str, Any]:
    end = {"09": "10", "10": "11"}[month]
    base: dict[str, Any] = {
        "case_id": CASE,
        "requested_intent": "observational_summary",
        "research_intent": "observational_summary",
        "target": "burned_area",
        "period_start": f"2015-{month}-01T00:00:00Z",
        "period_end": f"2015-{end}-01T00:00:00Z",
        "datasets": [
            {"dataset_id": MCD, "used_as": "burned_area"},
            {"dataset_id": FIRMS, "used_as": "active_fire", "role": "context"},
        ],
        "method_id": "mcd64a1_burned_area",
        "rationale": "MCD64A1 maps burned area; FIRMS is context only.",
    }
    return {**base, **overrides}


def test_build_plan_takes_facts_from_the_registry(workspace: Workspace) -> None:
    assert workspace.cases is not None
    plan = build_plan(
        PlanProposal.model_validate(proposal()),
        workspace.cases,
        load_registry(ROOT),
        question="How much burned in September?",
        task_id="t1",
        revision=1,
    )
    assert plan.selected.feasibility == "feasible"
    assert plan.dataset(MCD).valid_fraction_by_period  # from the manifest, not the model
    bad = proposal(datasets=[{"dataset_id": "made-up", "used_as": "burned_area"}])
    with pytest.raises(ValueError, match="unregistered datasets"):
        build_plan(
            PlanProposal.model_validate(bad),
            workspace.cases,
            load_registry(ROOT),
            question="q?",
            task_id="t1",
            revision=1,
        )


def test_tools_wait_for_a_plan_and_october_ends_in_a_typed_abstention(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            call("burned_area_summary", case_id=CASE, month="2015-10"),
            call("submit_plan", **proposal("10")),
            call(
                "declare_limitation",
                reasons=["insufficient_valid_data"],
                explanation="Too few valid land cells in that month.",
            ),
            say("The month fails the valid-data gate, so no area is claimed."),
        ]
    )
    result = investigate("October burned area?", client, workspace, tmp_path, options=PLAN)
    assert result.status is RunStatus.ABSTAINED
    assert [r.verdict for r in result.plan_reviews] == ["revise"]
    records = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    skipped = [r for r in records if r["event"] == "tool_skipped"]
    assert skipped and "submit_plan first" in skipped[0]["data"]["reason"]
    reply = next(
        r["data"]["data"]
        for r in records
        if r["event"] == "tool_result" and r["data"]["name"] == "submit_plan"
    )
    assert "insufficient_valid_data" in reply["suggested_reason_codes"]
    assert reply["revisions_left"] == 1
    events = load_run(tmp_path).events
    kinds = [e.event_type for e in events]
    assert "plan_submitted" in kinds and "plan_reviewed" in kinds
    review = next(e for e in events if e.event_type == "plan_reviewed")
    assert review.actor_role == "scientific_critic" and review.status == "rejected"
    assert review.plan_revision == 1
    saved = json.loads((tmp_path / "result.json").read_text())
    assert saved["plan_reviews"][0]["verdict"] == "revise"


def test_a_plan_rejected_twice_cannot_submit_claims(workspace: Workspace, tmp_path: Path) -> None:
    claim = {
        "case_id": CASE,
        "month": "2015-10",
        "quantity": "burned_area_ha",
        "value": 1.0,
        "statement": "Area mapped as burned.",
    }
    client = ScriptedClient(
        [
            call("submit_plan", **proposal("10")),
            call("submit_plan", **proposal("10")),
            call("submit_plan", **proposal("10")),
            call("submit_area_findings", claims=[claim]),
            say("No claim could be made."),
        ]
    )
    result = investigate("October burned area?", client, workspace, tmp_path, options=PLAN)
    assert len(result.plan_reviews) == 2
    assert result.area_ledger.rounds == []
    reasons = [
        json.loads(line)["data"]["reason"]
        for line in (tmp_path / "trace.jsonl").read_text().splitlines()
        if json.loads(line)["event"] == "tool_skipped"
    ]
    assert reasons == [
        "plan revision limit reached",
        "the plan was rejected after its revision; call declare_limitation",
    ]


def test_declare_limitation_runs_without_a_plan(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            call("declare_limitation", reasons=["out_of_scope"], explanation="No case fits it."),
            say("No registered case fits the question."),
        ]
    )
    result = investigate("Unrelated question?", client, workspace, tmp_path, options=PLAN)
    assert result.status is RunStatus.ABSTAINED and result.plan_reviews == ()


def test_download_requests_go_through_the_approval_gate(
    workspace: Workspace, tmp_path: Path
) -> None:
    assert workspace.cases is not None
    trace = RunTrace(tmp_path / "trace.jsonl")
    step = PlanStep(
        cases=workspace.cases,
        registry=shared_registry(),
        approvals=load_approvals(ROOT / "config" / "approvals"),
        trace=trace,
        task_id="gate-test",
        question="Did wind carry smoke over the box?",
    )
    extra = {"dataset_id": "era5-wind-2015", "used_as": "wind_vector"}
    reply = step.handle(
        PlanProposal.model_validate(proposal(datasets=[*proposal()["datasets"], extra]))
    )
    assert reply["approvals"] and reply["approvals"][0]["approved"] is False
    events = [r["event"] for r in trace.records()]
    assert events[-2:] == ["approval_requested", "approval_resolved"]


def test_plan_instructions_only_with_the_plan_step() -> None:
    assert PLAN_FIRST in system_prompt("low", plan_first=True)
    assert PLAN_FIRST not in system_prompt("low")
