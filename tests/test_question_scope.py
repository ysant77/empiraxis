"""A run answers the span the question names: the live NEA run was verified on a shorter one,
because a misleading period message led the product manager to cut the brief."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say

from earthlab.agent.loop import RunStatus
from earthlab.implement.bindings import BindingRefused
from earthlab.llm.providers import load_providers
from earthlab.planning.intent import asked_window
from earthlab.runtime import RunOptions, Workspace, investigate, open_workspace
from earthlab.trace import RunTrace
from earthlab.workflow.assign import repo_assignment
from earthlab.workflow.brief import validate_brief
from earthlab.workflow.contracts import BriefProposal
from earthlab.workflow.prompts import case_catalogue

ROOT = Path(__file__).resolve().parents[1]
SGT = ZoneInfo("Asia/Singapore")
QUESTION = "Which NEA region recorded the highest hourly PM2.5 in September and October 2015?"
FULL = (datetime(2015, 9, 1, tzinfo=SGT), datetime(2015, 11, 1, tzinfo=SGT))
NEA_PLAN = {
    "case_id": "nea-2015-haze",
    "requested_intent": "observational_summary",
    "research_intent": "observational_summary",
    "target": "air_pollution_observation",
    "period_start": "2015-09-01T00:00:00+08:00",
    "period_end": "2015-11-01T00:00:00+08:00",
    "datasets": [{"dataset_id": "nea-historical-1hr-pm25", "used_as": "air_pollution_observation"}],
    "method_id": "nea_hourly_episode",
    "rationale": "Rank the regions by their highest hourly value.",
}


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def peak(start: str, end: str) -> dict[str, Any]:
    return {
        "kind": "peak_region",
        "region": "west",
        "start": start,
        "end": end,
        "statement": "West recorded the highest value.",
    }


def test_the_named_months_give_a_whole_month_window() -> None:
    assert asked_window(QUESTION) == FULL
    assert asked_window("Peak in December 2015?") == (
        datetime(2015, 12, 1, tzinfo=SGT),
        datetime(2016, 1, 1, tzinfo=SGT),
    )


@pytest.mark.parametrize(
    "question",
    [
        "What was the value on 19 October 2015?",
        "What was the value on October 19, 2015?",
        "Which region had the highest value in October?",
        "Compare October 2015 with October 2016.",
        "Which region was highest?",
    ],
)
def test_no_window_is_assumed_when_the_question_does_not_fix_one(question: str) -> None:
    assert asked_window(question) is None


def brief(start: str, end: str) -> BriefProposal:
    return BriefProposal.model_validate(
        {
            "route": "engineer",
            "case_id": "nea-2015-haze",
            "normalized_question": QUESTION,
            "intent": "observational_summary",
            "period_start": start,
            "period_end": end,
        }
    )


def test_a_brief_cut_to_pass_the_check_is_refused(workspace: Workspace) -> None:
    assert workspace.cases is not None
    cut = brief("2015-09-01T00:00:00+00:00", "2015-10-31T00:00:00+00:00")
    assert any(
        "the span the request names" in i for i in validate_brief(cut, QUESTION, workspace.cases)
    )
    full = brief("2015-09-01T00:00:00+08:00", "2015-11-01T00:00:00+08:00")
    assert not validate_brief(full, QUESTION, workspace.cases)


def test_the_period_is_shown_in_the_case_zone(workspace: Workspace) -> None:
    assert workspace.cases is not None
    assert "2015-11-01T00:00:00+08:00" in case_catalogue(workspace.cases)
    late = brief("2015-09-01T00:00:00+08:00", "2015-11-02T00:00:00+08:00")
    assert any("+08:00" in i for i in validate_brief(late, QUESTION, workspace.cases))


def test_claims_on_a_shorter_window_cannot_be_verified(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            call("submit_plan", **NEA_PLAN),
            call(
                "submit_findings",
                claims=[peak("2015-09-01T08:00:00+08:00", "2015-10-31T08:00:00+08:00")],
            ),
            say("The west region is reported in R1.1."),
        ]
    )
    result = investigate(
        QUESTION, client, workspace, tmp_path, options=RunOptions(plan_review=True)
    )
    assert result.status is RunStatus.PARTIAL
    assert [
        e
        for e in RunTrace(tmp_path / "trace.jsonl").records()
        if e["event"] == "window_not_covered"
    ]


def test_claims_on_the_whole_window_are_verified(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            call("submit_plan", **NEA_PLAN),
            call(
                "submit_findings",
                claims=[peak("2015-09-01T00:00:00+08:00", "2015-11-01T00:00:00+08:00")],
            ),
            say("The west region is reported in R1.1."),
        ]
    )
    result = investigate(
        QUESTION, client, workspace, tmp_path, options=RunOptions(plan_review=True)
    )
    assert result.status is RunStatus.VERIFIED


def providers() -> dict[str, Any]:
    return load_providers(ROOT / "config" / "providers.yaml")


def test_one_provider_still_serves_every_role_by_default() -> None:
    config = providers()
    assignment = repo_assignment(config, ScriptedClient([], config["local-glimmer"]), ROOT)
    assert assignment.pm.candidate_id == assignment.engineer.candidate_id == "muse-glimmer"


def test_a_disabled_pm_provider_is_refused_before_any_call() -> None:
    config = providers()
    client = ScriptedClient([], config["local-glimmer"])
    with pytest.raises(BindingRefused):
        repo_assignment(
            config, client, ROOT, pm_client=ScriptedClient([], config["baseten-spark-open"])
        )
    assert not client.requests


def test_an_unbound_pm_provider_is_refused() -> None:
    config = providers()
    client = ScriptedClient([], config["local-glimmer"])
    with pytest.raises(BindingRefused, match="no candidate"):
        repo_assignment(
            config, client, ROOT, pm_client=ScriptedClient([], config["local-llama-guard"])
        )


def test_an_orchestrator_provider_needs_the_separate_topology() -> None:
    config = providers()
    client = ScriptedClient([], config["local-glimmer"])
    with pytest.raises(BindingRefused, match="separate"):
        repo_assignment(config, client, ROOT, orchestrator_client=client)
