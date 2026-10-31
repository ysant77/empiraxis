"""Combined and separate topologies, with the same scripted engineer and the same checks.

The separate topology adds one orchestrator call between the brief and the engineer. Its
decision is typed, validated by code, and cannot grant, approve or verify anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say
from test_workflow import CASE, REQUEST, brief, engineer_steps, plan
from workflow_helpers import assignment

from earthlab.agent.budget import Budget
from earthlab.events.adapter import load_run
from earthlab.implement.bindings import BindingRefused
from earthlab.llm.types import ProviderError, ProviderErrorKind
from earthlab.runtime import Workspace, open_workspace
from earthlab.workflow.assign import WorkflowAssignment
from earthlab.workflow.run import WorkflowRun, run_workflow

TOPOLOGIES = ["combined", "separate"]
ASSIGN = call(
    "submit_decision", decision="assign_engineer", case_id=CASE, reason="Brief is complete."
)


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def flow(
    topology: str, steps: list[Any], workspace: Workspace, run_dir: Path, **kw: Any
) -> tuple[WorkflowRun, ScriptedClient]:
    """Run with the brief first; the separate topology gets the orchestrator step next."""
    separate = topology == "separate"
    head, *rest = steps
    client = ScriptedClient([head, ASSIGN, *rest] if separate else steps)
    run = run_workflow(
        kw.pop("question", REQUEST), client, workspace, run_dir,
        assignment=assignment(client, separate=separate),
        orchestrator_client=client if separate else None, **kw,
    )  # fmt: skip
    return run, client


def records(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (run_dir / "trace.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_september_verifies_in_both_topologies(
    topology: str, workspace: Workspace, tmp_path: Path
) -> None:
    steps = [call("submit_brief", **brief()), *engineer_steps(), say("Verified in A1.1.")]
    run, client = flow(topology, steps, workspace, tmp_path)
    assert run.status == "verified" and run.reply is not None
    assert run.reply.supported_finding_ids == ("A1.1",)
    saved = json.loads((tmp_path / "result.json").read_text())["workflow"]
    assert saved["topology"] == topology
    events = load_run(tmp_path).events
    kinds = {e.event_type for e in events}
    actors = {e.actor_role for e in events}
    if topology == "separate":
        assert "orchestrator_decision_validated" in kinds and "orchestrator" in actors
        assert saved["orchestrator_decision"]["decision"]["decision"] == "assign_engineer"
        assert saved["usage"]["orchestrator"]["model_calls"] == 1
        assert {t["function"]["name"] for t in client.requests[1]["tools"]} == {"submit_decision"}
        order = [e.event_type for e in events]
        assert order.index("orchestrator_decision_validated") < order.index("task_handoff_created")
    else:
        assert "orchestrator_decision_validated" not in kinds and "orchestrator" not in actors
        assert saved["orchestrator_decision"] is None and "orchestrator" not in saved["usage"]


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_a_refused_request_makes_no_model_call(
    topology: str, workspace: Workspace, tmp_path: Path
) -> None:
    run, client = flow(
        topology, [call("submit_brief", **brief())], workspace, tmp_path,
        question="Should I wear a mask outside during the haze?",
    )  # fmt: skip
    assert run.status == "refused" and client.requests == []


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_october_abstains_in_both_topologies(
    topology: str, workspace: Workspace, tmp_path: Path
) -> None:
    october = brief(
        normalized_question="Mapped burned area in the Kalimantan study box, October 2015.",
        period_start="2015-10-01T00:00:00Z",
        period_end="2015-11-01T00:00:00Z",
    )
    steps = [
        call("submit_brief", **october),
        call("submit_plan", **plan("10")),
        call(
            "declare_limitation",
            reasons=["insufficient_valid_data"],
            explanation="Too few valid land cells in that month.",
        ),
        say("The month fails the valid-data gate, so no area is claimed."),
        say("No area was verified: the month has too little valid data."),
    ]
    question = "How much area burned in the Kalimantan study box in October 2015?"
    run, _ = flow(topology, steps, workspace, tmp_path, question=question)
    assert run.status == "abstained"
    assert run.manager.typed_limitations == ("insufficient_valid_data",)


@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_an_out_of_scope_download_never_reaches_the_approval_gate(
    topology: str, workspace: Workspace, tmp_path: Path
) -> None:
    wind = plan()
    wind["datasets"] = [
        *wind["datasets"],
        {"dataset_id": "era5-wind-2015", "used_as": "wind_vector"},
    ]
    steps = [
        call("submit_brief", **brief()),
        call("submit_plan", **wind),
        call("declare_limitation", reasons=["data_unavailable"], explanation="Not in scope."),
        say("No claim."),
        say("No finding."),
    ]
    flow(topology, steps, workspace, tmp_path)
    events = {r["event"] for r in records(tmp_path)}
    assert not events & {"approval_requested", "approval_resolved"}


def test_the_separate_topology_costs_one_more_call_so_a_tight_budget_stops_earlier(
    workspace: Workspace, tmp_path: Path
) -> None:
    steps = [call("submit_brief", **brief()), *engineer_steps(), say("Verified in A1.1.")]
    combined, _ = flow("combined", steps, workspace, tmp_path / "c", budget=Budget(max_turns=2))
    separate, _ = flow("separate", steps, workspace, tmp_path / "s", budget=Budget(max_turns=2))
    assert combined.engineer is not None and combined.engineer.turns == 1
    assert separate.status == "budget_exhausted" and separate.engineer is None


def run_separate(steps: list[Any], workspace: Workspace, run_dir: Path) -> WorkflowRun:
    client = ScriptedClient(steps)
    return run_workflow(
        REQUEST, client, workspace, run_dir,
        assignment=assignment(client, separate=True), orchestrator_client=client,
    )  # fmt: skip


def test_the_orchestrator_cannot_approve_or_grant_anything(
    workspace: Workspace, tmp_path: Path
) -> None:
    grab = call(
        "submit_decision", decision="assign_engineer", case_id=CASE, reason="Go.",
        approve_download=True,
    )  # fmt: skip
    run = run_separate([call("submit_brief", **brief()), grab, grab], workspace, tmp_path)
    assert run.status == "failed" and run.engineer is None
    reviews = [r["data"] for r in records(tmp_path) if r["event"] == "decision_reviewed"]
    assert len(reviews) == 2 and not any(r["valid"] for r in reviews)
    assert "approve_download" in reviews[0]["issues"][0]


def test_the_orchestrator_cannot_redirect_to_another_case(
    workspace: Workspace, tmp_path: Path
) -> None:
    other = call(
        "submit_decision", decision="assign_engineer", case_id="uttarakhand-2024-burned-area",
        reason="Try another case.",
    )  # fmt: skip
    steps = [call("submit_brief", **brief()), other, ASSIGN, *engineer_steps(), say("Ok A1.1.")]
    run = run_separate(steps, workspace, tmp_path)
    assert run.status == "verified" and run.task is not None and run.task.case_id == CASE
    reviews = [r["data"] for r in records(tmp_path) if r["event"] == "decision_reviewed"]
    assert [r["valid"] for r in reviews] == [False, True]


def test_request_input_and_decline_stop_before_the_engineer(
    workspace: Workspace, tmp_path: Path
) -> None:
    ask = call(
        "submit_decision", decision="request_input", reason="The area is unclear.",
        clarification="Which study box do you mean?",
    )  # fmt: skip
    run = run_separate([call("submit_brief", **brief()), ask], workspace, tmp_path / "a")
    assert run.status == "needs_input" and run.engineer is None
    assert run.manager.followup_questions == ("Which study box do you mean?",)
    no = call("submit_decision", decision="decline", reason="Outside the registered case.")
    run = run_separate([call("submit_brief", **brief()), no], workspace, tmp_path / "d")
    assert run.status == "out_of_scope" and run.engineer is None


def test_an_invented_number_in_a_clarification_is_rejected(
    workspace: Workspace, tmp_path: Path
) -> None:
    ask = call(
        "submit_decision", decision="request_input", reason="Need a threshold.",
        clarification="Use 500 ha as the threshold?",
    )  # fmt: skip
    run = run_separate([call("submit_brief", **brief()), ask, ask], workspace, tmp_path)
    assert run.status == "failed"
    reviews = [r["data"] for r in records(tmp_path) if r["event"] == "decision_reviewed"]
    assert "numbers not in the request or the brief: 500" in reviews[0]["issues"]


def test_an_orchestrator_provider_error_fails_closed(workspace: Workspace, tmp_path: Path) -> None:
    steps = [call("submit_brief", **brief()), ProviderError(ProviderErrorKind.AUTH, "HTTP 401")]
    run = run_separate(steps, workspace, tmp_path)
    assert run.status == "provider_error" and run.engineer is None
    assert load_run(tmp_path).status == "provider_error"


def test_topology_and_orchestrator_binding_must_agree(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([])
    separate = assignment(client, separate=True)
    with pytest.raises(BindingRefused, match="needs an orchestrator client"):
        run_workflow(REQUEST, client, workspace, tmp_path, assignment=separate)
    with pytest.raises(ValueError, match="separate topology, and only it"):
        WorkflowAssignment(separate.pm, separate.engineer, "separate", None)
    assert separate.orchestrator is not None
    assert separate.orchestrator.implementation == "experimental"
