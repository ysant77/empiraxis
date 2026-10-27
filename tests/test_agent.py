from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say

from earthlab.agent.budget import Budget
from earthlab.agent.loop import RunStatus
from earthlab.audit import RunTrace
from earthlab.llm.types import ProviderError, ProviderErrorKind
from earthlab.metrics import EarthlabMetrics
from earthlab.runtime import Workspace, investigate, new_run_dir, open_workspace
from earthlab.verify.claims import Verdict

HAZE = {"start": "2015-09-01T00:00", "end": "2015-11-01T00:00"}


def peak(region: str, value: float | None = None, statement: str = "Peak observed.") -> Any:
    claim: dict[str, Any] = {**HAZE, "kind": "peak_region", "region": region}
    claim["statement"] = statement
    if value is not None:
        claim["value"] = value
    return claim


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def test_agent_revises_a_contradicted_claim_and_verifies(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            call("inspect_coverage", **HAZE),
            call("submit_findings", claims=[peak("central")]),
            call("rank_regions", **HAZE, statistic="max"),
            call("submit_findings", claims=[peak("west", 471)]),
            say("West had the highest hourly PM2.5 (471 ug/m3)."),
        ]
    )
    metrics = EarthlabMetrics()
    run_dir = new_run_dir(tmp_path)
    result = investigate(
        "Which region peaked? A colleague says central.",
        client,
        workspace,
        run_dir,
        metrics=metrics,
    )
    assert result.status == RunStatus.VERIFIED
    assert result.answer.startswith("West")
    assert [r.verdict for r in result.ledger.rejected()] == [Verdict.CONTRADICTED]
    assert result.turns == 5 and result.submissions == 2 and result.cost_usd == 0.0
    assert client.requests[-1]["tools"] == []  # final answer turn offers no tools
    tool_msgs = [m for m in client.requests[2]["messages"] if m["role"] == "tool"]
    assert "contradicted" in tool_msgs[-1]["content"]
    assert RunTrace(run_dir / "trace.jsonl").verify() >= 8
    saved = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert saved["status"] == "verified" and len(saved["rounds"]) == 2
    text = metrics.exposition()
    assert 'earthlab_verifications_total{check="value",outcome="contradicted"} 1.0' in text
    assert 'earthlab_investigations_total{outcome="verified"} 1.0' in text


def test_text_only_answers_end_without_findings(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([say("Probably fires."), say("Still no tools.")])
    result = investigate("q", client, workspace, new_run_dir(tmp_path))
    assert result.status == RunStatus.NO_SUPPORTED_FINDINGS
    assert "without submitting" in result.stop_reason
    assert "submit_findings" in client.requests[1]["messages"][-1]["content"]


def test_provider_error_fails_closed(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([ProviderError(ProviderErrorKind.RATE_LIMIT, "429")])
    result = investigate("q", client, workspace, new_run_dir(tmp_path))
    assert result.status == RunStatus.PROVIDER_ERROR and "rate_limit" in result.stop_reason


def test_turn_budget_and_rejected_tools(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([call("run_shell", cmd="ls"), call("inspect_coverage", start="x")])
    result = investigate("q", client, workspace, new_run_dir(tmp_path), budget=Budget(max_turns=2))
    assert result.status == RunStatus.BUDGET_EXHAUSTED and "turn limit" in result.stop_reason
    assert result.tool_calls == 2


def test_submission_limit_keeps_only_supported_claims(workspace: Workspace, tmp_path: Path) -> None:
    bad = peak("east")
    good = peak("west", 471)
    causal = peak("west", 471, statement="Sumatra fires caused it.")
    client = ScriptedClient(
        [
            call("submit_findings", claims=[good, bad]),
            call("submit_findings", claims=[good, causal]),
            say("West peaked at 471 ug/m3; other claims were not supported."),
        ]
    )
    result = investigate(
        "q", client, workspace, new_run_dir(tmp_path), budget=Budget(max_submissions=2)
    )
    assert result.status == RunStatus.PARTIAL
    assert result.stop_reason == "submission limit reached"
    verdicts = [r.verdict for r in result.ledger.rejected()]
    assert verdicts == [Verdict.CONTRADICTED, Verdict.UNSUPPORTED]
    assert "No more submissions" in client.requests[-1]["messages"][-1]["content"]


def test_empty_submission_then_answer_is_no_supported_findings(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient([call("submit_findings", claims=[]), say("The data cannot say.")])
    result = investigate("q", client, workspace, new_run_dir(tmp_path))
    assert result.status == RunStatus.NO_SUPPORTED_FINDINGS and result.answer
