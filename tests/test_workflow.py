"""The product manager -> Geospatial Engineer workflow, with a scripted Glimmer client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say
from workflow_helpers import assignment

from earthlab.events.adapter import load_run
from earthlab.llm.providers import load_providers
from earthlab.llm.types import ProviderError, ProviderErrorKind
from earthlab.runtime import Workspace, open_workspace
from earthlab.trace import RunTrace
from earthlab.workflow.contracts import BriefProposal
from earthlab.workflow.run import WorkflowRun, run_workflow, validate_brief

CASE = "kalimantan-2015-burned-area"
MCD = "mcd64a1-061-kalimantan-2015"
FIRMS = "firms-modis-sp-kalimantan-2015"
SEPT_HA = 77426.0
REQUEST = "How much area burned in the Kalimantan study box in September 2015?"


def flow(
    question: str, client: ScriptedClient, workspace: Workspace, run_dir: Path, **kw: Any
) -> WorkflowRun:
    return run_workflow(question, client, workspace, run_dir, assignment=assignment(client), **kw)


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def brief(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "route": "engineer",
        "case_id": CASE,
        "normalized_question": "Mapped burned area in the Kalimantan study box, September 2015.",
        "intent": "observational_summary",
        "target_quantity": "burned_area_ha",
        "period_start": "2015-09-01T00:00:00Z",
        "period_end": "2015-10-01T00:00:00Z",
    }
    return {**base, **overrides}


def plan(month: str = "09", case_id: str = CASE) -> dict[str, Any]:
    end = {"09": "10", "10": "11"}[month]
    return {
        "case_id": case_id,
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


def area_claim(value: float = SEPT_HA) -> dict[str, Any]:
    return {
        "case_id": CASE,
        "month": "2015-09",
        "quantity": "burned_area_ha",
        "value": value,
        "statement": "Mapped burned area after quality checks.",
    }


def engineer_steps() -> list[Any]:
    return [
        call("submit_plan", **plan()),
        call("burned_area_summary", case_id=CASE, month="2015-09"),
        call("submit_area_findings", claims=[area_claim()]),
        say("The mapped burned area for the study box is in A1.1; it is not forest loss."),
    ]


def records(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (run_dir / "trace.jsonl").read_text().splitlines()]


def test_september_request_goes_pm_to_engineer_and_returns_verified(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            call("submit_brief", **brief()),
            *engineer_steps(),
            say("The engineer verified the mapped burned area in A1.1. It is not forest loss."),
        ]
    )
    run = flow(REQUEST, client, workspace, tmp_path)
    assert run.status == "verified"
    assert run.task is not None and run.task.case_id == CASE
    assert run.task.allowed_method_ids == ("mcd64a1_burned_area",)
    assert run.reply is not None and run.reply.supported_finding_ids == ("A1.1",)
    assert run.reply.critic_verdicts[0] in ("accept", "accept_with_warnings")
    assert run.manager.report_source == "pm_model"
    assert run.manager.verified_finding_refs == ("A1.1",)
    # The PM saw only its own tool; the engineer saw the scientific tools.
    pm_tools = {t["function"]["name"] for t in client.requests[0]["tools"]}
    assert pm_tools == {"submit_brief"}
    engineer_tools = {t["function"]["name"] for t in client.requests[1]["tools"]}
    assert {"submit_plan", "burned_area_summary"} <= engineer_tools
    assert "submit_brief" not in engineer_tools
    assert client.requests[-1]["tools"] == [] and client.requests[-1]["tool_choice"] == "none"
    # One hash chain, real role events, and a result.json that agrees with it.
    assert RunTrace(tmp_path / "trace.jsonl").verify() > 0
    events = load_run(tmp_path).events
    actors = {e.actor_role for e in events}
    assert {"product_manager", "geospatial_engineer", "scientific_critic", "verifier"} <= actors
    assert "orchestrator" not in actors
    kinds = [e.event_type for e in events]
    for kind in (
        "brief_validated",
        "task_handoff_created",
        "role_invocation_started",
        "role_invocation_finished",
        "verified_result_delivered",
        "pm_report_issued",
    ):
        assert kind in kinds
    assert kinds.index("brief_validated") < kinds.index("task_handoff_created")
    assert kinds.index("task_handoff_created") < kinds.index("plan_submitted")
    handoff = next(e for e in events if e.event_type == "task_handoff_created")
    assert handoff.receiver_role == "geospatial_engineer" and len(handoff.evidence_refs) == 2
    saved = json.loads((tmp_path / "result.json").read_text())
    assert saved["status"] == "verified" and saved["question"] == REQUEST
    assert saved["workflow"]["engineering_task"]["brief_sha256"] == run.task.brief_sha256


def test_a_missing_threshold_returns_needs_input_without_an_engineer(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            call(
                "submit_brief",
                **brief(
                    route="needs_input",
                    case_id="nea-2015-haze",
                    normalized_question="Hours above a PM2.5 threshold in the west region.",
                    target_quantity=None,
                    period_start=None,
                    period_end=None,
                    clarifications_needed=["Which PM2.5 threshold, in ug/m3?"],
                ),
            )
        ]
    )
    run = flow("How many hours was the west region very polluted?", client, workspace, tmp_path)
    assert run.status == "needs_input" and run.task is None and run.engineer is None
    assert run.manager.followup_questions == ("Which PM2.5 threshold, in ug/m3?",)
    assert len(client.requests) == 1
    assert not any(r["event"] in ("start", "tool_result") for r in records(tmp_path))
    assert load_run(tmp_path).status == "needs_input"


def test_a_number_the_request_did_not_contain_is_rejected(
    workspace: Workspace, tmp_path: Path
) -> None:
    invented = brief(normalized_question="Check whether 500 ha burned in September 2015.")
    client = ScriptedClient([call("submit_brief", **invented), call("submit_brief", **invented)])
    run = flow(REQUEST, client, workspace, tmp_path)
    assert run.status == "failed" and run.engineer is None
    reviews = [r["data"] for r in records(tmp_path) if r["event"] == "brief_reviewed"]
    assert len(reviews) == 2 and not any(r["valid"] for r in reviews)
    assert "numbers not in the request or the case: 500" in reviews[0]["issues"]


def test_one_correction_then_the_handoff(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            call("submit_brief", **brief(case_id="borneo-made-up")),
            call("submit_brief", **brief()),
            *engineer_steps(),
            say("Verified in A1.1."),
        ]
    )
    run = flow(REQUEST, client, workspace, tmp_path)
    assert run.status == "verified" and run.pm_calls == 3  # two briefs and the report
    reviews = [r["data"] for r in records(tmp_path) if r["event"] == "brief_reviewed"]
    assert [r["valid"] for r in reviews] == [False, True]
    assert "not registered" in reviews[0]["issues"][0]


def test_the_pm_cannot_run_a_scientific_tool(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            call("burned_area_summary", case_id=CASE, month="2015-09"),
            call("burned_area_summary", case_id=CASE, month="2015-09"),
        ]
    )
    run = flow(REQUEST, client, workspace, tmp_path)
    assert run.status == "failed"
    assert not any(r["event"] == "tool_result" for r in records(tmp_path))


def test_the_engineer_cannot_plan_outside_its_assigned_case(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            call("submit_brief", **brief()),
            call("submit_plan", **plan(case_id="uttarakhand-2024-burned-area")),
            call("assess_case", case_id="uttarakhand-2024-burned-area"),
            call(
                "declare_limitation",
                reasons=["out_of_scope"],
                explanation="The plan named another case.",
            ),
            say("No claim was made."),
            say("No finding was verified."),
        ]
    )
    run = flow(REQUEST, client, workspace, tmp_path)
    plans = [
        r["data"]
        for r in records(tmp_path)
        if r["event"] == "tool_result" and r["data"]["name"] == "submit_plan"
    ]
    assert plans[0]["outcome"] != "executed"
    skipped = [r["data"]["name"] for r in records(tmp_path) if r["event"] == "tool_skipped"]
    assert skipped == ["assess_case"]  # no reviewed plan, so no evidence tool runs
    assert run.reply is not None and run.reply.supported_finding_ids == ()


def test_a_pm_report_with_figures_falls_back_to_the_engineer_answer(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            call("submit_brief", **brief()),
            *engineer_steps(),
            say("About 77,426 ha burned in September 2015."),
        ]
    )
    run = flow(REQUEST, client, workspace, tmp_path)
    assert run.status == "verified" and run.manager.report_source == "engineer"
    assert "77" not in run.manager.report_text
    report = next(r["data"] for r in records(tmp_path) if r["event"] == "pm_report")
    assert report["passed"] is False and report["issues"]


def test_a_refused_question_never_reaches_the_pm(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([call("submit_brief", **brief())])
    run = flow("Should I wear a mask outside during the haze?", client, workspace, tmp_path)
    assert run.status == "refused" and client.requests == []
    assert load_run(tmp_path).status == "refused"


def test_october_ends_in_an_abstention_reported_by_the_pm(
    workspace: Workspace, tmp_path: Path
) -> None:
    october = brief(
        normalized_question="Mapped burned area in the Kalimantan study box, October 2015.",
        period_start="2015-10-01T00:00:00Z",
        period_end="2015-11-01T00:00:00Z",
    )
    client = ScriptedClient(
        [
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
    )
    run = flow(
        "How much area burned in the Kalimantan study box in October 2015?",
        client,
        workspace,
        tmp_path,
    )
    assert run.status == "abstained"
    assert run.reply is not None and run.reply.critic_verdicts == ("revise",)
    assert run.manager.typed_limitations == ("insufficient_valid_data",)
    assert run.manager.report_source == "pm_model"


def test_a_provider_error_in_the_pm_fails_closed(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([ProviderError(ProviderErrorKind.SERVER, "HTTP 500")])
    run = flow(REQUEST, client, workspace, tmp_path)
    assert run.status == "provider_error" and run.engineer is None
    assert load_run(tmp_path).status == "provider_error"


def test_brief_validation_rules(workspace: Workspace) -> None:
    assert workspace.cases is not None
    cases = workspace.cases

    def issues(**overrides: Any) -> list[str]:
        return validate_brief(BriefProposal.model_validate(brief(**overrides)), REQUEST, cases)

    assert issues() == []
    assert issues(case_id=None) == ["route engineer needs a registered case_id"]
    assert issues(clarifications_needed=["x?"])
    assert issues(route="needs_input")
    assert issues(period_end=None) == ["give both period_start and period_end, or neither"]
    assert (
        "outside the case period"
        in issues(period_start="2016-09-01T00:00:00Z", period_end="2016-10-01T00:00:00Z")[0]
    )


def test_workflow_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from earthlab import cli

    steps = [call("submit_brief", **brief()), *engineer_steps(), say("Verified in A1.1.")]
    glimmer = load_providers(Path("config/providers.yaml"))["local-glimmer"]
    monkeypatch.setattr(cli, "build_client", lambda config: ScriptedClient(steps, glimmer))
    argv = ["--data-dir", str(REPO_DATA), "workflow", REQUEST, "--guard", "none"]
    code = cli.main([*argv, "--runs-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0 and "brief: route engineer" in out and "status: verified (pm_model)" in out
    run_dir = next(tmp_path.iterdir())
    assert (run_dir / "report.md").is_file()


def test_a_workflow_run_replays_offline(workspace: Workspace, tmp_path: Path) -> None:
    from earthlab.verify.replay import replay_run

    steps = [call("submit_brief", **brief()), *engineer_steps(), say("Verified in A1.1.")]
    flow(REQUEST, ScriptedClient(steps), workspace, tmp_path)
    out = replay_run(tmp_path, workspace)
    assert list(out.area) == [1, 1] and not out.problems


def test_an_unverified_engineer_answer_is_never_reported(
    workspace: Workspace, tmp_path: Path
) -> None:
    steps = [
        call("submit_brief", **brief()),
        *engineer_steps()[:-1],
        say("About 77,426 ha burned."),  # fails the answer audit
        say("Still 77,426 ha."),  # the one revision fails too
    ]
    run = flow(REQUEST, ScriptedClient(steps), workspace, tmp_path)
    assert run.status == "answer_unverified"
    assert run.manager.report_text == "" and run.manager.report_source == "none"
    assert not any(r["event"] == "pm_report" for r in records(tmp_path))
