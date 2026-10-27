"""Regression tests: a run is verified only when its claims AND its final text pass."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say

from earthlab import cli
from earthlab.agent.budget import Budget
from earthlab.agent.loop import RunStatus
from earthlab.report.markdown import render_report
from earthlab.runtime import Workspace, investigate, new_run_dir, open_workspace, result_payload
from earthlab.verify.answer_audit import audit_answer
from earthlab.verify.claims import Check, Claim, Verdict, VerificationResult

HAZE = {"start": "2015-09-01T00:00", "end": "2015-11-01T00:00"}


def claim(kind: str, region: str, value: float) -> dict[str, Any]:
    return {**HAZE, "kind": kind, "region": region, "value": value, "statement": "Observed."}


WEST_PEAK = claim("peak_region", "west", 471)
CENTRAL_MAX = claim("region_max", "central", 267)


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def run(workspace: Workspace, tmp_path: Path, answer: str, *claims: dict[str, Any]) -> Any:
    """The scripted model repeats its text when asked to revise it."""
    client = ScriptedClient(
        [call("submit_findings", claims=list(claims)), say(answer), say(answer)]
    )
    return investigate("Which region peaked?", client, workspace, new_run_dir(tmp_path))


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        ("West peaked at 471 ug/m3; central reached 267.", RunStatus.VERIFIED),
        ("The highest reading, 471, was in the west.", RunStatus.VERIFIED),
        ("West peaked at 471 ug/m3, about 12 times a typical day.", RunStatus.ANSWER_UNVERIFIED),
        ("Central peaked at 471 ug/m3.", RunStatus.ANSWER_UNVERIFIED),
        ("West reached 267 and central reached 471.", RunStatus.ANSWER_UNVERIFIED),
        ("West peaked at 471 because fires sent smoke.", RunStatus.ANSWER_UNVERIFIED),
        ("West peaked at 471; people should stay indoors.", RunStatus.ANSWER_UNVERIFIED),
    ],
)
def test_status_needs_a_bound_and_in_scope_answer(
    workspace: Workspace, tmp_path: Path, answer: str, status: RunStatus
) -> None:
    result = run(workspace, tmp_path, answer, WEST_PEAK, CENTRAL_MAX)
    assert len(result.ledger.supported()) == 2
    assert result.status is status
    assert bool(result.answer_issues) is (status is RunStatus.ANSWER_UNVERIFIED)


def test_a_number_seen_only_in_tool_output_does_not_ground_the_answer(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            call("rank_regions", **HAZE, statistic="max"),
            call("submit_findings", claims=[WEST_PEAK]),
            say("West peaked at 471; south reached 353."),
            say("West peaked at 471; south reached 353."),
        ]
    )
    result = investigate("Which region peaked?", client, workspace, new_run_dir(tmp_path))
    assert result.status is RunStatus.ANSWER_UNVERIFIED
    assert result.answer_audit is not None and result.answer_audit.ungrounded == (353.0,)


def test_partial_run_with_unbound_text_is_downgraded(workspace: Workspace, tmp_path: Path) -> None:
    wrong = claim("region_max", "east", 999)
    client = ScriptedClient(
        [
            call("submit_findings", claims=[WEST_PEAK, wrong]),
            call("submit_findings", claims=[WEST_PEAK, wrong]),
            call("submit_findings", claims=[WEST_PEAK, wrong]),
            say("West peaked at 471 and east at 999."),
            say("West peaked at 471 and east at 999."),
        ]
    )
    result = investigate("Which region peaked?", client, workspace, new_run_dir(tmp_path))
    assert result.status is RunStatus.ANSWER_UNVERIFIED
    assert result.answer_audit is not None and result.answer_audit.ungrounded == (999.0,)


def test_one_revision_can_fix_the_text(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            call("submit_findings", claims=[WEST_PEAK]),
            say("West peaked at 471; south reached 353."),
            say("West peaked at 471."),
        ]
    )
    run_dir = new_run_dir(tmp_path)
    result = investigate("Which region peaked?", client, workspace, run_dir)
    assert result.status is RunStatus.VERIFIED and result.answer == "West peaked at 471."
    assert result.turns == 3 and "353 matches no supported claim" in str(client.requests[-1])
    assert '"answer_revision"' in (run_dir / "trace.jsonl").read_text(encoding="utf-8")


def test_no_revision_once_the_budget_is_spent(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([call("submit_findings", claims=[WEST_PEAK]), say("West 471, east 9.")])
    budget = Budget(max_turns=2)
    result = investigate("q", client, workspace, new_run_dir(tmp_path), budget=budget)
    assert result.status is RunStatus.ANSWER_UNVERIFIED and result.turns == 2


def test_audit_binds_each_number_to_the_nearest_region() -> None:
    supported = [_supported(WEST_PEAK), _supported(CENTRAL_MAX)]
    ok = audit_answer("Central's maximum (267) stayed below the west's 471.", supported)
    assert ok.passed and ok.numbers_checked == 2
    swapped = audit_answer("Central's maximum (471) stayed below the west's 267.", supported)
    assert not swapped.passed and len(swapped.misattributed) == 2
    hypothesis = audit_answer("The claimed 300 for central is not supported.", supported, "300?")
    assert hypothesis.passed


def test_threshold_of_a_supported_claim_counts_as_evidence() -> None:
    above = claim("hours_above", "west", 44) | {"threshold": 200}
    audit = audit_answer("West was above 200 for 44 hours.", [_supported(above)])
    assert audit.passed


def test_report_renders_findings_from_claims_and_flags_the_text(
    workspace: Workspace, tmp_path: Path
) -> None:
    result = run(workspace, tmp_path, "Central peaked at 471 ug/m3.", WEST_PEAK, CENTRAL_MAX)
    payload = result_payload("q", result, workspace.snapshot)
    first = payload["findings"][0]
    assert first["id"] == "R1.1" and first["unit"] == "ug/m3"
    assert first["source_sha256"] == workspace.snapshot.sha256
    report = render_report(payload)
    assert "## Findings" in report and "| R1.2 | region_max | central |" in report
    assert "## Interpretation" in report and "NOT VERIFIED" in report
    assert "471 is next to central" in report


def test_cli_exit_code_is_non_zero_for_an_unverified_answer() -> None:
    assert cli.exit_code("verified") == 0 and cli.exit_code("partial") == 0
    assert cli.exit_code("answer_unverified") == 2 and cli.exit_code("refused") == 2


def test_inconsistent_timestamps_and_missing_data_never_verify(workspace: Workspace) -> None:
    with pytest.raises(ValueError, match="end"):
        Claim.model_validate(claim("region_max", "west", 471) | {"end": "2015-08-01T00:00"})
    empty = claim("region_max", "west", 1) | {"start": "2030-01-01", "end": "2030-01-02"}
    verdict = workspace.verifier.verify(Claim.model_validate(empty)).verdict
    assert verdict is Verdict.INSUFFICIENT_DATA


def _supported(raw: dict[str, Any]) -> VerificationResult:
    parsed = Claim.model_validate(raw)
    return VerificationResult(
        claim=parsed, verdict=Verdict.SUPPORTED, check=Check.VALUE, observed=parsed.value, reason=""
    )
