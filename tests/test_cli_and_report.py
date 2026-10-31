from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say

from earthlab import cli
from earthlab.console import print_event
from earthlab.report.markdown import render_report
from earthlab.report.write import write_report
from earthlab.runtime import investigate, new_run_dir, open_workspace

HAZE = {"start": "2015-09-01T00:00", "end": "2015-11-01T00:00"}
CLAIM = {**HAZE, "kind": "peak_region", "region": "west", "value": 471, "statement": "West."}


def run_scripted(tmp_path: Path) -> Path:
    client = ScriptedClient(
        [
            call("submit_findings", claims=[{**CLAIM, "region": "central", "value": None}]),
            call("submit_findings", claims=[CLAIM]),
            say("West had the highest value (R2.1)."),
        ]
    )
    run_dir = new_run_dir(tmp_path)
    investigate("Which region peaked?", client, open_workspace(REPO_DATA), run_dir)
    return run_dir


def test_report_and_replay_from_saved_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = run_scripted(tmp_path)
    report = write_report(run_dir, REPO_DATA)
    text = report.read_text(encoding="utf-8")
    assert "**contradicted**" in text and "## Findings (verified claims)" in text
    assert "_No supported findings._" not in text
    assert "pm25_hourly.png" in text and (run_dir / "pm25_hourly.png").stat().st_size > 1000
    assert "not health advice" in text.lower()
    assert cli.main(["--data-dir", str(REPO_DATA), "replay", str(run_dir)]) == 0
    assert "verdicts reproduced: 2/2" in capsys.readouterr().out


def test_replay_detects_a_tampered_verdict(tmp_path: Path) -> None:
    run_dir = run_scripted(tmp_path)
    path = run_dir / "result.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    result["rounds"][0][0]["verdict"] = "supported"
    path.write_text(json.dumps(result), encoding="utf-8")
    assert cli.main(["--data-dir", str(REPO_DATA), "replay", str(run_dir)]) == 1


def test_qa_and_verify_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--data-dir", str(REPO_DATA), "qa"]) == 0
    assert '"missing_hours": 0' in capsys.readouterr().out
    assert cli.main(["--data-dir", str(REPO_DATA), "verify", json.dumps(CLAIM)]) == 0
    wrong = json.dumps({**CLAIM, "region": "east"})
    assert cli.main(["--data-dir", str(REPO_DATA), "verify", wrong]) == 1
    assert '"contradicted"' in capsys.readouterr().out


def test_progress_printer_formats_events(capsys: pytest.CaptureFixture[str]) -> None:
    print_event({"event": "model_turn", "data": {"turn": 1, "tool_calls": [], "wall_seconds": 2.0}})
    verdicts = {"verdicts": [{"kind": "peak_region", "region": "west", "verdict": "supported"}]}
    print_event(
        {
            "event": "tool_result",
            "data": {"name": "submit_findings", "outcome": "executed", "data": verdicts},
        }
    )
    print_event(
        {"event": "tool_result", "data": {"name": "x", "outcome": "rejected", "error": "bad"}}
    )
    print_event({"event": "finish", "data": {"status": "verified", "reason": "done"}})
    out = capsys.readouterr().out
    assert "text answer" in out and "west=supported" in out and "| bad" in out
    assert "status=verified" in out


def test_report_without_rounds_or_chart() -> None:
    result: dict[str, Any] = {
        "question": "q",
        "status": "no_supported_findings",
        "stop_reason": "x",
        "answer": "",
        "rounds": [],
        "provider": "p",
        "model": "m",
        "served_model": None,
        "turns": 1,
        "tool_calls": 0,
        "submissions": 0,
        "seconds": 1.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "estimated_cost_usd": None,
        "attribution": "a",
        "source": {
            "source_url": "u",
            "sha256": "s",
            "unit": "ug/m3",
            "timezone": "SGT",
            "licence": "l",
        },
    }
    text = render_report(result)
    assert "_None._" in text and "not priced" in text and "Observed data" not in text


def test_guard_can_be_disabled_and_safety_events_print(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.build_guard(Path("config/providers.yaml"), "none") is None
    guard = cli.build_guard(
        Path(__file__).resolve().parents[1] / "config" / "providers.yaml", "local-llama-guard"
    )
    assert guard is not None and guard.name == "llama-guard-3-8b"
    blocked = {"stage": "question", "allowed": False, "blocked_by": "scope_rules", "guard": None}
    print_event({"event": "safety_check", "data": blocked})
    assert "BLOCKED by scope_rules | rules only" in capsys.readouterr().out
