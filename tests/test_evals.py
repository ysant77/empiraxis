from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say

from earthlab import cli
from earthlab.evals.runner import run_suite
from earthlab.evals.tasks import load_tasks
from earthlab.llm.types import ProviderError, ProviderErrorKind
from earthlab.runtime import Workspace, open_workspace

TASKS = load_tasks(Path(__file__).resolve().parents[1] / "evals" / "tasks.yaml")
PEAK_TASK = next(t for t in TASKS if t.id == "peak-region-haze-2015")
HAZE = {"start": "2015-09-01T00:00", "end": "2015-11-01T00:00"}


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def no_tool_reply(region: str) -> str:
    claim = {**HAZE, "kind": "peak_region", "region": region, "statement": "Peak."}
    return "Here you go: " + json.dumps({"claims": [claim]})


def test_all_arms_on_one_task(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            call(
                "submit_findings",
                claims=[
                    {
                        **HAZE,
                        "kind": "peak_region",
                        "region": "west",
                        "value": 471,
                        "statement": "West peaked.",
                    }
                ],
            ),
            say("West."),
            say(no_tool_reply("east")),
        ]
    )
    summary = run_suite([PEAK_TASK], ["agent", "no_tools", "scripted"], workspace, tmp_path, client)
    arms = summary["arms"]
    assert arms["agent"]["verified_success"] == 1
    assert arms["no_tools"]["verified_success"] == 0 and arms["no_tools"]["rejected_claims"] == 1
    assert arms["scripted"]["requirements_met"] == "1/1"
    rows = (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 3 and json.loads(rows[1])["verdicts"] == ["contradicted"]


def test_no_tool_arm_failures(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [say("I am not sure."), ProviderError(ProviderErrorKind.TIMEOUT, "slow")]
    )
    summary = run_suite([PEAK_TASK, PEAK_TASK], ["no_tools"], workspace, tmp_path, client)
    assert summary["arms"]["no_tools"]["verified_success"] == 0
    details = [json.loads(r)["detail"] for r in (tmp_path / "runs.jsonl").read_text().splitlines()]
    assert details[0]["error"] == "unparseable claims"
    assert details[0]["reply_head"] == "I am not sure." and details[0]["finish_reason"] == "stop"
    assert details[1] == {"error": "timeout"}
    bad_json = ScriptedClient([say('{"claims": [{"kind": "nonsense"}]}')])
    summary = run_suite([PEAK_TASK], ["no_tools"], workspace, tmp_path / "b", bad_json)
    assert summary["arms"]["no_tools"]["verified_success"] == 0


def test_model_arms_need_a_client(workspace: Workspace, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="needs a model client"):
        run_suite([PEAK_TASK], ["agent"], workspace, tmp_path)


def test_scripted_eval_command(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    args = [
        "--data-dir",
        str(REPO_DATA),
        "eval",
        "--arms",
        "scripted",
        "--runs-dir",
        str(tmp_path),
        "--only",
        "west-hours-above-200",
    ]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "west-hours-above-200 [scripted] met 1/1 success=True" in out
    with pytest.raises(SystemExit, match="unknown arms"):
        cli.main(["eval", "--arms", "oracle"])
