"""Workflow observability: the view built from a recorded run, and the Control Room panel.

All runs here are scripted, and the view must say so.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import FAKE_CONFIG, ScriptedClient, call, say
from test_workflow import CASE, REQUEST, brief, engineer_steps
from workflow_helpers import assignment

from earthlab.events.workflow_view import load_workflow
from earthlab.llm.client import OpenAICompatClient
from earthlab.llm.retry import RetryPolicy
from earthlab.llm.types import ChatResponse, ProviderError, ProviderErrorKind, Usage
from earthlab.runtime import RunOptions, Workspace, open_workspace
from earthlab.trace import TraceIntegrityError
from earthlab.workflow.calls import client_kind
from earthlab.workflow.run import run_workflow

ROOT = Path(__file__).resolve().parents[1]
ASSIGN = call(
    "submit_decision", decision="assign_engineer", case_id=CASE, reason="Brief is complete."
)
STEPS = [call("submit_brief", **brief()), *engineer_steps(), say("Verified in A1.1.")]


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def run(client: ScriptedClient, workspace: Workspace, run_dir: Path, **kw: Any) -> None:
    separate = kw.pop("separate", False)
    run_workflow(
        REQUEST, client, workspace, run_dir, assignment=assignment(client, separate=separate),
        orchestrator_client=client if separate else None, **kw,
    )  # fmt: skip


class NoUsage(ScriptedClient):
    def chat(self, *args: Any, **kwargs: Any) -> ChatResponse:
        return super().chat(*args, **kwargs).model_copy(update={"usage": Usage()})


class OtherServed(ScriptedClient):
    def chat(self, *args: Any, **kwargs: Any) -> ChatResponse:
        return super().chat(*args, **kwargs).model_copy(update={"served_model": "qwen3-coder"})


def test_a_combined_run_shows_its_stages_and_per_role_use(
    workspace: Workspace, tmp_path: Path
) -> None:
    run(ScriptedClient(STEPS), workspace, tmp_path)
    view = load_workflow(tmp_path)
    assert view is not None
    assert (view.topology, view.provenance, view.status) == ("combined", "synthetic", "verified")
    stages = [s["stage"] for s in view.stages]
    for stage in ("PM brief", "Engineer assignment", "Plan review (deterministic critic)",
                  "Tool call", "Verified result to PM", "PM report", "Run finished"):  # fmt: skip
        assert stage in stages
    assert "Orchestrator decision" not in stages
    tools = [s["detail"] for s in view.stages if s["stage"] == "Tool call"]
    assert tools == ["submit_plan", "burned_area_summary", "submit_area_findings"]
    roles = {r["role"]: r for r in view.roles}
    pm = roles["Product manager (model)"]
    assert (pm["calls"], pm["prompt tokens"], pm["completion tokens"]) == (2, 200, 20)
    assert pm["served matches"] is True and pm["provider"] == FAKE_CONFIG.name
    engineer = roles["Geospatial engineer (Muse investigator, plan-reviewed)"]
    assert engineer["calls"] == 4 and engineer["status"] == "experimental"
    assert view.findings == ["A1.1"] and view.retries == []
    assert view.budget["used"]["model_calls"] == 6


def test_a_separate_run_names_the_model_orchestrator(workspace: Workspace, tmp_path: Path) -> None:
    head, *rest = STEPS
    run(ScriptedClient([head, ASSIGN, *rest]), workspace, tmp_path, separate=True)
    view = load_workflow(tmp_path)
    assert view is not None and view.topology == "separate"
    assert "Model orchestrator (separate topology)" in {r["role"] for r in view.roles}
    decision = next(s for s in view.stages if s["stage"] == "Orchestrator decision")
    assert decision["status"] == "accepted" and decision["detail"] == "assign_engineer"


def test_unreported_tokens_stay_unknown(workspace: Workspace, tmp_path: Path) -> None:
    """Regression: missing usage was summed as zero in the ledger."""
    run(NoUsage(STEPS), workspace, tmp_path)
    view = load_workflow(tmp_path)
    assert view is not None
    pm = next(r for r in view.roles if r["role"] == "Product manager (model)")
    assert pm["prompt tokens"] is None and pm["completion tokens"] is None
    usage = json.loads((tmp_path / "result.json").read_text())["workflow"]["usage"]
    assert usage["product_manager"]["prompt_tokens"] is None
    assert usage["total"]["prompt_tokens"] is None


def test_a_served_model_that_is_not_the_bound_one_is_flagged(
    workspace: Workspace, tmp_path: Path
) -> None:
    run(OtherServed(STEPS), workspace, tmp_path)
    view = load_workflow(tmp_path)
    assert view is not None
    pm = next(r for r in view.roles if r["role"] == "Product manager (model)")
    assert pm["served model"] == "qwen3-coder" and pm["served matches"] is False


def test_retries_and_failures_are_listed(workspace: Workspace, tmp_path: Path) -> None:
    steps = [ProviderError(ProviderErrorKind.SERVER, "HTTP 500"), *STEPS]
    retry = RunOptions(provider_retry=RetryPolicy(delay_seconds=0.0, max_delay_seconds=0.0))
    run(ScriptedClient(steps), workspace, tmp_path, options=retry)
    view = load_workflow(tmp_path)
    assert view is not None
    assert [(r["role"], r["kind"], r["attempt"], r["retrying"]) for r in view.retries] == [
        ("product_manager", "server", 1, True)
    ]
    pm = next(r for r in view.roles if r["role"] == "Product manager (model)")
    assert pm["failed calls"] == 1 and pm["calls"] == 3


def test_investigator_replays_are_not_workflow_runs() -> None:
    for name in ("sb05-september", "sb05b-october"):
        assert load_workflow(ROOT / "examples" / "replay" / name) is None


def test_a_broken_chain_is_refused(workspace: Workspace, tmp_path: Path) -> None:
    run(ScriptedClient(STEPS), workspace, tmp_path)
    path = tmp_path / "trace.jsonl"
    path.write_text(path.read_text().replace("submit_brief", "submit_briefX", 1))
    with pytest.raises(TraceIntegrityError):
        load_workflow(tmp_path)


def test_provenance_comes_from_the_client_class(workspace: Workspace, tmp_path: Path) -> None:
    assert client_kind(ScriptedClient([])) == "scripted_or_other"
    live = OpenAICompatClient(FAKE_CONFIG)
    assert client_kind(live) == "live_http"
    live.close()
    run(ScriptedClient(STEPS), workspace, tmp_path)
    path = tmp_path / "trace.jsonl"
    start = json.loads(path.read_text().splitlines()[0])
    assert start["data"]["client_kinds"] == {
        "product_manager": "scripted_or_other", "geospatial_engineer": "scripted_or_other",
    }  # fmt: skip
