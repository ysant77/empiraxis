"""Defects the rotated live matrix found: each test keeps one of them fixed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say
from test_plan_step import CASE, PLAN, proposal
from test_workflow import brief
from test_workflow_topology import run_separate

from earthlab.agent.area_findings import AreaLedger
from earthlab.agent.findings import FindingsLedger
from earthlab.agent.limitations import LimitationArgs, ReasonCode
from earthlab.agent.loop import RunStatus
from earthlab.agent.rendered import render_answer, verified_block
from earthlab.report.evidence import month_or_error
from earthlab.report.write import write_report
from earthlab.runtime import Workspace, investigate, open_workspace
from earthlab.safety.gate import CAUSAL_ABSTENTION
from earthlab.safety.scope import answer_out_of_scope
from earthlab.verify.replay import replay_run

OCTOBER = "How much area burned in the Kalimantan study box in October 2015?"
CAUSAL = "Did plantation clearing cause the burned area in Kalimantan in September 2015?"
DECLARE = {"reasons": ["insufficient_valid_data"], "explanation": "The month fails the gate."}


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def refused_october(workspace: Workspace, run_dir: Path) -> Any:
    client = ScriptedClient(
        [
            call("submit_plan", **proposal("10")),
            call("declare_limitation", **DECLARE),
            say("The month does not meet the quality gate, so no area is reported."),
        ]
    )
    return investigate(OCTOBER, client, workspace, run_dir, options=PLAN)


def test_a_refused_month_is_recorded_and_replays(workspace: Workspace, tmp_path: Path) -> None:
    result = refused_october(workspace, tmp_path)
    assert result.status is RunStatus.ABSTAINED
    saved = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    (month,) = saved["evidence"]["months"]
    assert month["month"] == "2015-10" and not month["check"]["gate_ok"]
    assert workspace.cases is not None
    assert month == month_or_error(workspace.cases, CASE, "2015-10")
    replay = replay_run(tmp_path, workspace)
    assert replay.ok and replay.months == [1, 1] and replay.files_checked > 0


def test_the_reader_sees_why_the_month_was_refused(workspace: Workspace, tmp_path: Path) -> None:
    result = refused_october(workspace, tmp_path)
    block = verified_block(result.ledger, result.area_ledger, result.limitations)
    assert "Deterministic plan review:" in block and "valid fraction" in block
    assert "Verified findings" not in block


def test_a_passing_plan_records_no_gate_note(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [call("submit_plan", **proposal()), call("declare_limitation", **DECLARE), say("None.")]
    )
    result = investigate(OCTOBER, client, workspace, tmp_path, options=PLAN)
    assert result.area_ledger.gate_notes == [] and result.area_ledger.consulted == []


def test_the_limit_of_a_gate_is_not_read_as_a_cause() -> None:
    text = (
        "The limitation is recorded because the MCD64A1 coverage for the requested month in "
        "the Kalimantan study box is below the quality gate."
    )
    assert answer_out_of_scope(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Burned area rose because peat dried, and the quality gate passed.",
        "Haze rose because fires spread; the data are not missing.",
        "West peaked because of smoke, though some records were missing elsewhere.",
    ],
)
def test_a_cause_beside_a_gate_word_is_still_a_cause(text: str) -> None:
    assert answer_out_of_scope(text) == "the answer asserts a cause the data cannot show"


def test_the_rendered_fallback_does_not_point_at_a_block_it_does_not_have() -> None:
    limits = [
        LimitationArgs(
            reasons=[ReasonCode.INSUFFICIENT_VALID_DATA], explanation="The month fails the gate."
        )
    ]
    text = render_answer(FindingsLedger(), AreaLedger(), limits)
    assert text is not None and "above" not in text


def out_of_scope_brief(**changes: Any) -> dict[str, Any]:
    fields = brief() | {"route": "out_of_scope", "case_id": None}
    fields |= {"period_start": None, "period_end": None}
    return fields | changes


def test_a_causal_out_of_scope_brief_gives_the_causal_abstention(
    workspace: Workspace, tmp_path: Path
) -> None:
    pm = call(
        "submit_brief",
        **out_of_scope_brief(intent="causal_inference", normalized_question=CAUSAL),
    )
    run = run_separate([pm], workspace, tmp_path)
    assert run.status == "out_of_scope" and run.engineer is None
    assert run.manager.report_text == CAUSAL_ABSTENTION
    assert run.manager.report_source == "rendered"
    assert run.manager.typed_limitations == ("causation_not_identifiable",)


def test_a_plain_out_of_scope_brief_tells_the_reader_no_analysis_ran(
    workspace: Workspace, tmp_path: Path
) -> None:
    run = run_separate([call("submit_brief", **out_of_scope_brief())], workspace, tmp_path)
    assert run.manager.report_text.startswith("No analysis ran")
    assert run.manager.typed_limitations == ()


def test_a_run_stopped_before_the_engineer_replays(workspace: Workspace, tmp_path: Path) -> None:
    run_separate([call("submit_brief", **out_of_scope_brief())], workspace, tmp_path)
    replay = replay_run(tmp_path, workspace)
    assert replay.ok and replay.source_matches and replay.pm25 == [0, 0]


def test_a_direct_run_without_verdict_records_fails_replay(
    workspace: Workspace, tmp_path: Path
) -> None:
    refused_october(workspace, tmp_path)
    path = tmp_path / "result.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    del saved["rounds"]
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert "the run has no verdict records" in replay_run(tmp_path, workspace).problems


def test_a_limitation_only_run_has_no_pm25_chart(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "result.json").write_text(json.dumps(_causal_result()), encoding="utf-8")
    text = write_report(run_dir, REPO_DATA).read_text(encoding="utf-8")
    assert "causation_not_identifiable" in text
    assert "pm25_hourly.png" not in text and not (run_dir / "pm25_hourly.png").exists()


def _causal_result() -> dict[str, Any]:
    source = {"source_url": "u", "sha256": "s", "unit": "ug/m3", "timezone": "z", "licence": "l"}
    limitation = {"reasons": ["causation_not_identifiable"], "explanation": "Cause is not shown."}
    return {
        "question": "q", "status": "abstained", "stop_reason": "x", "answer": "a", "rounds": [],
        "provider": "p", "model": "m", "served_model": "m", "turns": 1, "tool_calls": 1,
        "submissions": 0, "seconds": 1.0, "prompt_tokens": 1, "completion_tokens": 1,
        "estimated_cost_usd": 0.0, "attribution": "t", "source": source,
        "limitations": [limitation],
    }  # fmt: skip
