"""Regression tests: a run is verified only when its claims AND its interpretation pass.

The interpretation may cite finding IDs but holds no digits, dates or month names; the
Findings table, rendered from supported claims, carries every number.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say

from earthlab import cli
from earthlab.agent.budget import Budget
from earthlab.agent.loop import RunStatus
from earthlab.evals.runner import run_suite
from earthlab.evals.tasks import EvalTask
from earthlab.llm.types import ProviderError, ProviderErrorKind
from earthlab.report.markdown import render_report
from earthlab.runtime import Workspace, investigate, new_run_dir, open_workspace, result_payload
from earthlab.verify.claims import Claim, Verdict

HAZE = {"start": "2015-09-01T00:00", "end": "2015-11-01T00:00"}


def claim(kind: str, region: str, value: float | None, **extra: Any) -> dict[str, Any]:
    return {**HAZE, "kind": kind, "region": region, "value": value, "statement": "Seen.", **extra}


WEST_PEAK = claim("peak_region", "west", 471)
WEST_MAX = claim("region_max", "west", 471)
CENTRAL_MAX = claim("region_max", "central", 267)
CENTRAL_MEAN = claim("region_mean", "central", 57.9)
GOOD = "West had the highest hourly value (R1.1); central stayed lower (R1.2)."
FIXED = "West had the highest hourly value (R1.1)."


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def run(
    workspace: Workspace, tmp_path: Path, text: str, *claims: dict[str, Any], **kwargs: Any
) -> Any:
    """The scripted model repeats its text when asked to revise it."""
    steps = [call("submit_findings", claims=list(claims)), say(text), say(text)]
    question = kwargs.pop("question", "Which region peaked?")
    client = ScriptedClient(steps)
    return investigate(question, client, workspace, new_run_dir(tmp_path), **kwargs)


@pytest.mark.parametrize(
    ("text", "issue"),
    [
        ("Central peaked at 999.", "numbers in the text (999)"),
        ("The central mean was 267 (R1.2).", "numbers in the text (267)"),
        ("In October central reached its peak (R1.2).", "dates in the text (October)"),
        ("West peaked on the night of the 19th (R1.1).", "numbers in the text (19)"),
        ("Central was above the threshold for many hours (R1.2).", None),
        ("Central had the highest value (R1.2).", "'highest' for central"),
        ("Central was higher than west (R1.2).", "contradicts the supported claims"),
        ("West peaked, as R1.7 shows.", "R1.7 is not a supported finding"),
        ("West had the highest value because fires sent smoke.", "cause"),
    ],
)
def test_misleading_or_numeric_text_is_not_verified(
    workspace: Workspace, tmp_path: Path, text: str, issue: str | None
) -> None:
    result = run(workspace, tmp_path, text, WEST_PEAK, CENTRAL_MAX)
    assert len(result.ledger.supported()) == 2
    if issue is None:
        assert result.status is RunStatus.VERIFIED
        return
    assert result.status is RunStatus.ANSWER_UNVERIFIED
    assert any(issue in found for found in result.answer_issues), result.answer_issues


def test_clean_interpretation_is_verified(workspace: Workspace, tmp_path: Path) -> None:
    result = run(workspace, tmp_path, GOOD, WEST_PEAK, CENTRAL_MAX)
    assert result.status is RunStatus.VERIFIED and not result.answer_issues


def test_comparison_needs_matching_kind_and_window(workspace: Workspace, tmp_path: Path) -> None:
    ok = run(workspace, tmp_path, "West was higher than central.", WEST_MAX, CENTRAL_MAX)
    assert ok.status is RunStatus.VERIFIED
    mixed = run(workspace, tmp_path, "West was higher than central.", WEST_MAX, CENTRAL_MEAN)
    assert mixed.status is RunStatus.ANSWER_UNVERIFIED
    assert "no pair of supported claims" in mixed.answer_issues[0]
    mean = run(workspace, tmp_path, "Central's mean was higher than west.", WEST_MAX, CENTRAL_MAX)
    assert mean.status is RunStatus.ANSWER_UNVERIFIED


def test_question_numbers_never_become_observations(workspace: Workspace, tmp_path: Path) -> None:
    question = "Did central peak at 999?"
    result = run(workspace, tmp_path, "Central peaked at 999.", CENTRAL_MAX, question=question)
    assert result.status is RunStatus.ANSWER_UNVERIFIED
    rejected = "The claimed central peak in the question is not supported (R1.1)."
    verdict = run(workspace, tmp_path, rejected, CENTRAL_MAX, question=question)
    assert verdict.status is RunStatus.VERIFIED


def test_missing_final_text_is_not_verified(workspace: Workspace, tmp_path: Path) -> None:
    """The turn limit stops the run after a supported submission, before any text."""
    client = ScriptedClient([call("submit_findings", claims=[WEST_PEAK])])
    budget = Budget(max_turns=1)
    result = investigate("q", client, workspace, new_run_dir(tmp_path), budget=budget)
    assert result.answer == "" and len(result.ledger.supported()) == 1
    assert result.status is RunStatus.ANSWER_UNVERIFIED
    assert result.answer_issues == ("no final text was produced",)


@pytest.mark.parametrize(
    ("revision", "note"),
    [
        (ProviderError(ProviderErrorKind.TIMEOUT, "slow"), "revision failed: timeout"),
        (say(""), "revision returned no text"),
        (call("rank_regions", **HAZE, statistic="max"), "revision returned no text"),
    ],
)
def test_failed_revision_keeps_the_original_text(
    workspace: Workspace, tmp_path: Path, revision: Any, note: str
) -> None:
    """A timeout, an empty text or a tool call never replaces the text or runs a tool."""
    client = ScriptedClient(
        [call("submit_findings", claims=[WEST_PEAK]), say("West peaked at 471."), revision]
    )
    result = investigate("Which region peaked?", client, workspace, new_run_dir(tmp_path))
    assert result.status is RunStatus.ANSWER_UNVERIFIED and result.answer == "West peaked at 471."
    assert result.answer_issues[-1] == note
    assert client.requests[-1]["tool_choice"] == "none" and result.tool_calls == 1


def test_revision_on_the_partial_path_is_text_only(workspace: Workspace, tmp_path: Path) -> None:
    wrong = claim("region_max", "east", 999)
    client = ScriptedClient(
        [call("submit_findings", claims=[WEST_PEAK, wrong]), say("West peaked at 471."), say(FIXED)]
    )
    result = investigate("Which region peaked?", client, workspace, new_run_dir(tmp_path))
    assert client.requests[-1]["tool_choice"] == "none"
    assert result.status is RunStatus.PARTIAL and result.answer == FIXED


def test_one_revision_can_fix_the_text(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [call("submit_findings", claims=[WEST_PEAK]), say("West peaked at 471."), say(FIXED)]
    )
    run_dir = new_run_dir(tmp_path)
    result = investigate("Which region peaked?", client, workspace, run_dir)
    assert result.status is RunStatus.VERIFIED and result.turns == 3
    assert "numbers in the text (471)" in json.dumps(client.requests[-1]["messages"][-1])
    assert '"answer_revision"' in (run_dir / "trace.jsonl").read_text(encoding="utf-8")


def test_no_revision_once_the_budget_is_spent(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([call("submit_findings", claims=[WEST_PEAK]), say("West 471.")])
    budget = Budget(max_turns=2)
    result = investigate("q", client, workspace, new_run_dir(tmp_path), budget=budget)
    assert result.status is RunStatus.ANSWER_UNVERIFIED and result.turns == 2


@pytest.mark.parametrize(
    ("text", "status"), [(GOOD, "verified"), ("West 471.", "answer_unverified")]
)
def test_every_surface_reports_the_same_status(
    workspace: Workspace, tmp_path: Path, text: str, status: str
) -> None:
    """result.json, the report, the CLI exit code and the eval score agree."""
    result = run(workspace, tmp_path, text, WEST_PEAK, CENTRAL_MAX)
    payload = result_payload("q", result, workspace.snapshot)
    report = render_report(payload)
    assert payload["status"] == status and f"**Status:** `{status}`" in report
    assert ("NOT VERIFIED" in report) is (status != "verified")
    assert cli.exit_code(status) == (0 if status == "verified" else 2)
    task = EvalTask.model_validate(
        {
            "id": "peak",
            "question": "Which region peaked?",
            "requirements": [{"kind": "peak_region", **HAZE}],
        }
    )
    answer = FIXED if status == "verified" else text
    client = ScriptedClient([call("submit_findings", claims=[WEST_PEAK]), say(answer), say(answer)])
    summary = run_suite([task], ["agent"], workspace, tmp_path / "eval", client)
    assert summary["arms"]["agent"]["verified_success"] == (1 if status == "verified" else 0)


def test_report_renders_findings_from_claims(workspace: Workspace, tmp_path: Path) -> None:
    result = run(workspace, tmp_path, GOOD, WEST_PEAK, CENTRAL_MAX)
    payload = result_payload("q", result, workspace.snapshot)
    first = payload["findings"][0]
    assert first["id"] == "R1.1" and first["unit"] == "ug/m3"
    assert first["source_sha256"] == workspace.snapshot.sha256
    report = render_report(payload)
    assert "| R1.2 | region_max | central |" in report and "| 267 | ug/m3 |" in report
    assert "## Interpretation" in report and "Answer check passed" in report


def test_partial_status_is_not_a_cli_success() -> None:
    assert cli.exit_code("verified") == 0
    assert cli.exit_code("partial") == 2 and cli.exit_code("answer_unverified") == 2


def test_inconsistent_timestamps_and_missing_data_never_verify(workspace: Workspace) -> None:
    with pytest.raises(ValueError, match="end"):
        Claim.model_validate(claim("region_max", "west", 471) | {"end": "2015-08-01T00:00"})
    empty = claim("region_max", "west", 1) | {"start": "2030-01-01", "end": "2030-01-02"}
    verdict = workspace.verifier.verify(Claim.model_validate(empty)).verdict
    assert verdict is Verdict.INSUFFICIENT_DATA
