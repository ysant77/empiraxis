from __future__ import annotations

from pathlib import Path

from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say

from earthlab.agent.loop import RunStatus
from earthlab.report.markdown import render_report
from earthlab.runtime import investigate, new_run_dir, open_workspace, result_payload
from earthlab.verify.answer_audit import answer_numbers, audit_answer

HAZE = {"start": "2015-09-01T00:00", "end": "2015-11-01T00:00"}


def test_dates_hours_years_and_units_are_not_counted() -> None:
    text = (
        "On 19 October 2015 at 23:00 (2015-10-19T23:00+08:00), PM2.5 in the west reached "
        "471 ug/m3 over 1-hour, with 1,464 hours and a mean of 65.5 µg/m³ in Oct 3."
    )
    assert answer_numbers(text) == [471.0, 1464.0, 65.5]


def test_rounding_and_question_numbers_without_a_region() -> None:
    assert audit_answer("Mean 65.5, threshold 150.", [], "Mean 65.54? Above 150?").passed
    bad = audit_answer("The peak was 999 ug/m3.", [])
    assert bad.ungrounded == (999.0,) and not bad.passed
    assert bad.problems() == ["number 999 matches no supported claim"]


def test_invented_number_in_final_answer_is_flagged(tmp_path: Path) -> None:
    claim = {**HAZE, "kind": "peak_region", "region": "west", "value": 471, "statement": "West."}
    client = ScriptedClient(
        [
            call("rank_regions", **HAZE, statistic="max"),
            call("submit_findings", claims=[claim]),
            say("West peaked at 471 ug/m3, about 12 times the 38 ug/m3 norm."),
            say("West peaked at 471 ug/m3, about 12 times the 38 ug/m3 norm."),
        ]
    )
    workspace = open_workspace(REPO_DATA)
    result = investigate("Which region peaked?", client, workspace, new_run_dir(tmp_path))
    assert result.status is RunStatus.ANSWER_UNVERIFIED
    assert result.answer_audit is not None
    assert result.answer_audit.ungrounded == (12.0, 38.0)
    payload = result_payload("q", result, workspace.snapshot)
    assert payload["answer_audit"]["ungrounded"] == [12.0, 38.0]
    assert "number 12 matches no supported claim" in render_report(payload)
    payload["answer_issues"] = []
    assert "all 3 numbers match a supported claim" in render_report(payload)
