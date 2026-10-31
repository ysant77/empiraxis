"""Workflow hardening: one shared budget, runtime role bindings, task scope, PM retries.

Each test pins a gap found in the workflow merged in #51 and fails on that code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import FAKE_CONFIG, ScriptedClient, call, say
from test_workflow import CASE, REQUEST, brief, engineer_steps, plan
from workflow_helpers import assignment, bindings, candidate

from earthlab.agent.budget import Budget
from earthlab.agent.findings import FindingsLedger
from earthlab.implement.bindings import BindingRefused, load_bindings
from earthlab.llm.providers import load_providers
from earthlab.llm.retry import RetryPolicy
from earthlab.llm.types import ProviderError, ProviderErrorKind
from earthlab.runtime import RunOptions, Workspace, build_registry, open_workspace
from earthlab.workflow.assign import AREA_TOOLS, PM25_TOOLS, resolve_assignment
from earthlab.workflow.run import WorkflowRun, run_workflow

ROOT = Path(__file__).resolve().parents[1]
HAZE = "nea-2015-haze"
RETRY = RunOptions(provider_retry=RetryPolicy(delay_seconds=0.0, max_delay_seconds=0.0))


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def flow(steps: list[Any], workspace: Workspace, run_dir: Path, **kw: Any) -> WorkflowRun:
    client = ScriptedClient(steps)
    return run_workflow(REQUEST, client, workspace, run_dir, assignment=assignment(client), **kw)


def records(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (run_dir / "trace.jsonl").read_text().splitlines()]


def executed(run_dir: Path) -> list[str]:
    return [
        r["data"]["name"]
        for r in records(run_dir)
        if r["event"] == "tool_result" and r["data"]["outcome"] == "executed"
    ]


# --- one budget for the whole run -------------------------------------------------------


def test_the_engineer_gets_only_the_turns_the_pm_left(workspace: Workspace, tmp_path: Path) -> None:
    """Old code gave each stage the full budget: one PM call plus four engineer turns ran."""
    steps = [call("submit_brief", **brief()), *engineer_steps(), say("Verified in A1.1.")]
    run = flow(steps, workspace, tmp_path, budget=Budget(max_turns=4))
    # Three engineer turns: claims are verified but no final text fits, so not verified.
    assert run.engineer is not None and run.engineer.turns == 3
    assert run.status == "answer_unverified"
    total = json.loads((tmp_path / "result.json").read_text())["workflow"]["usage"]["total"]
    assert total["model_calls"] <= 4


def test_no_engineer_when_the_pm_used_the_whole_budget(
    workspace: Workspace, tmp_path: Path
) -> None:
    run = flow([call("submit_brief", **brief())], workspace, tmp_path, budget=Budget(max_turns=1))
    assert run.status == "budget_exhausted" and run.engineer is None
    assert "model-call limit 1" in run.manager.typed_limitations[0]
    assert not any(r["event"] == "start" for r in records(tmp_path))


def test_the_pm_report_is_skipped_when_nothing_is_left(
    workspace: Workspace, tmp_path: Path
) -> None:
    steps = [call("submit_brief", **brief()), *engineer_steps(), say("never sent")]
    run = flow(steps, workspace, tmp_path, budget=Budget(max_turns=5))
    assert run.status == "verified" and run.manager.report_source == "engineer"
    report = next(r["data"] for r in records(tmp_path) if r["event"] == "pm_report")
    assert report["passed"] is False and "limit" in report["issues"][0]


def test_per_role_usage_is_recorded(workspace: Workspace, tmp_path: Path) -> None:
    steps = [call("submit_brief", **brief()), *engineer_steps(), say("Verified in A1.1.")]
    flow(steps, workspace, tmp_path)
    usage = json.loads((tmp_path / "result.json").read_text())["workflow"]["usage"]
    assert usage["product_manager"]["model_calls"] == 2  # brief and report
    assert usage["geospatial_engineer"]["model_calls"] == 4
    assert usage["geospatial_engineer"]["tool_calls"] == 3
    assert usage["total"]["model_calls"] == 6


# --- runtime role bindings --------------------------------------------------------------


def test_a_client_that_is_not_the_bound_one_is_refused(
    workspace: Workspace, tmp_path: Path
) -> None:
    """Old code ran any client in any role. Now nothing is written before the refusal."""
    bound = assignment(ScriptedClient([]))
    other = ScriptedClient([], config=FAKE_CONFIG.model_copy(update={"model": "qwen3-coder"}))
    with pytest.raises(BindingRefused, match="bound to fake-glimmer/muse-glimmer-30B"):
        run_workflow(REQUEST, other, workspace, tmp_path, assignment=bound)
    assert not (tmp_path / "trace.jsonl").exists()


@pytest.mark.parametrize(
    ("overrides", "status", "reason"),
    [
        ({}, "planned", "planned, not implemented"),
        ({"roles": ["geospatial_engineer"]}, "experimental", "not listed for product_manager"),
        ({"provider_id": "elsewhere"}, "experimental", "provider is not configured"),
        ({"model_id": "other-model"}, "experimental", "client model"),
    ],
)
def test_resolution_names_the_failed_gate(
    overrides: dict[str, Any], status: str, reason: str
) -> None:
    client = ScriptedClient([])
    with pytest.raises(BindingRefused, match=reason):
        resolve_assignment(
            bindings(candidate(**overrides), status=status), {FAKE_CONFIG.name: FAKE_CONFIG},
            client, client, pm_candidate="fake-glimmer", engineer_candidate="fake-glimmer",
        )  # fmt: skip


def test_a_disabled_provider_and_an_experimental_role_without_opt_in_are_refused() -> None:
    off = FAKE_CONFIG.model_copy(update={"enabled": False})
    state = bindings().status("product_manager", "fake-glimmer", {off.name: off})
    assert "provider is disabled" in state.blockers(allow_experimental=True)
    live = bindings().status("product_manager", "fake-glimmer", {FAKE_CONFIG.name: FAKE_CONFIG})
    assert live.blockers(allow_experimental=True) == []
    assert live.blockers() == ["product_manager is experimental; it needs an explicit opt-in"]


def test_repository_bindings_keep_the_four_facts_apart() -> None:
    repo = load_bindings(ROOT / "config" / "roles" / "bindings.yaml")
    providers = load_providers(ROOT / "config" / "providers.yaml")
    pm = repo.status("product_manager", "muse-glimmer", providers)
    assert (pm.implementation, pm.provider, pm.preflight, pm.licence) == (
        "experimental", "available", "passed", "approved",
    )  # fmt: skip
    qwen = repo.status("implementor", "qwen3-coder-30b-a3b", providers)
    assert (qwen.implementation, qwen.provider, qwen.preflight, qwen.licence) == (
        "planned", "not_configured", "not_run", "not_checked",
    )  # fmt: skip
    assert not qwen.approved_for_use and not qwen.listed


# --- the engineer stays inside its task -------------------------------------------------


def test_a_burned_area_engineer_cannot_use_the_pm25_tools(
    workspace: Workspace, tmp_path: Path
) -> None:
    """Old code registered the NEA PM2.5 tools for every case."""
    steps = [
        call("submit_brief", **brief()),
        call("submit_plan", **plan()),
        call("inspect_coverage", start="2015-09-01T00:00", end="2015-10-01T00:00"),
        call("declare_limitation", reasons=["out_of_scope"], explanation="Wrong tool."),
        say("No claim."),
        say("No finding."),
    ]
    client = ScriptedClient(steps)
    run_workflow(REQUEST, client, workspace, tmp_path, assignment=assignment(client))
    engineer_tools = {t["function"]["name"] for t in client.requests[1]["tools"]}
    assert not engineer_tools & PM25_TOOLS
    assert "inspect_coverage" not in executed(tmp_path)
    rejected = next(
        r["data"]
        for r in records(tmp_path)
        if r["event"] == "tool_result" and r["data"]["name"] == "inspect_coverage"
    )
    assert rejected["error"] == "unknown tool"


def test_a_haze_engineer_cannot_use_the_burned_area_tools(
    workspace: Workspace, tmp_path: Path
) -> None:
    haze = brief(
        case_id=HAZE,
        normalized_question="Highest hourly PM2.5 region in September 2015.",
        target_quantity=None,
        period_start=None,
        period_end=None,
    )
    client = ScriptedClient([call("submit_brief", **haze), say("stop"), say("stop")])
    question = "Which region had the highest hourly PM2.5 in September 2015?"
    run = run_workflow(question, client, workspace, tmp_path, assignment=assignment(client))
    assert run.task is not None and not set(run.task.allowed_tool_names) & AREA_TOOLS
    engineer_tools = {t["function"]["name"] for t in client.requests[1]["tools"]}
    assert engineer_tools >= PM25_TOOLS and not engineer_tools & AREA_TOOLS


def test_a_plan_naming_another_case_dataset_is_refused(
    workspace: Workspace, tmp_path: Path
) -> None:
    """Old code let a Kalimantan plan register the NEA dataset from another case."""
    cross = plan()
    nea = {
        "dataset_id": "nea-historical-1hr-pm25",
        "used_as": "air_pollution_observation",
        "role": "context",
    }
    cross["datasets"] = [*cross["datasets"], nea]
    steps = [
        call("submit_brief", **brief()),
        call("submit_plan", **cross),
        call("declare_limitation", reasons=["out_of_scope"], explanation="Plan refused."),
        say("No claim."),
        say("No finding."),
    ]
    flow(steps, workspace, tmp_path)
    result = next(
        r["data"]
        for r in records(tmp_path)
        if r["event"] == "tool_result" and r["data"]["name"] == "submit_plan"
    )
    assert result["outcome"] != "executed" and "unregistered" in (result["error"] or "")


def test_a_plan_under_revision_cannot_reach_evidence_in_the_workflow(
    workspace: Workspace, tmp_path: Path
) -> None:
    steps = [
        call("submit_brief", **brief()),
        call("submit_plan", **plan("10")),
        call("burned_area_summary", case_id=CASE, month="2015-10"),
        call(
            "declare_limitation",
            reasons=["insufficient_valid_data"],
            explanation="Too few valid cells.",
        ),
        say("No claim."),
        say("No finding."),
    ]
    flow(steps, workspace, tmp_path)
    assert "burned_area_summary" not in executed(tmp_path)


def test_scope_tool_names_match_the_registered_tools(workspace: Workspace) -> None:
    """Guard against drift: every scoped tool name exists in the real registry."""
    names = set(build_registry(workspace, FindingsLedger()).names())
    assert names | {"submit_plan"} >= (PM25_TOOLS | AREA_TOOLS)


# --- PM calls retry like the investigator's ---------------------------------------------


def test_a_pm_server_error_is_retried_once_under_the_policy(
    workspace: Workspace, tmp_path: Path
) -> None:
    """Old code never retried a PM call, whatever the run's retry policy."""
    steps = [
        ProviderError(ProviderErrorKind.SERVER, "HTTP 500"),
        call("submit_brief", **brief()),
        *engineer_steps(),
        say("Verified in A1.1."),
    ]
    run = flow(steps, workspace, tmp_path, options=RETRY)
    assert run.status == "verified"
    errors = [r["data"] for r in records(tmp_path) if r["event"] == "model_error"]
    assert [(e["role"], e["attempt"], e["retrying"]) for e in errors] == [
        ("product_manager", 1, True)
    ]


def test_a_pm_retry_needs_room_in_the_budget(workspace: Workspace, tmp_path: Path) -> None:
    steps = [ProviderError(ProviderErrorKind.SERVER, "HTTP 500"), call("submit_brief", **brief())]
    run = flow(steps, workspace, tmp_path, options=RETRY, budget=Budget(max_turns=1))
    assert run.status == "provider_error"
    assert any(r["event"] == "model_retry_skipped" for r in records(tmp_path))


def test_a_malformed_pm_reply_is_not_retried(workspace: Workspace, tmp_path: Path) -> None:
    steps = [
        ProviderError(ProviderErrorKind.MALFORMED, "bad body"),
        call("submit_brief", **brief()),
    ]
    run = flow(steps, workspace, tmp_path, options=RETRY)
    assert run.status == "provider_error"
    assert sum(r["event"] == "model_error" for r in records(tmp_path)) == 1
