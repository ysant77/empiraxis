"""E2: every bench row carries the run metrics, the summary never hides an unknown cost or
a false verification, and the hashes of the files that define a run are recorded."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from fake_client import FAKE_CONFIG, ScriptedClient, call, say

from earthlab.bench.metrics import CAVEAT, CONFIG_FILES, arm_summary, config_hashes
from earthlab.bench.runner import run_bench
from earthlab.bench.scenarios import Outcome, ScenarioScore, load_scenarios
from earthlab.llm.types import ProviderError, ProviderErrorKind
from earthlab.runtime import Workspace, open_workspace

ROOT = Path(__file__).resolve().parents[1]
BY_ID = {s.id: s for s in load_scenarios(ROOT / "evals" / "sciencebench_dev_v1.yaml")}
PRICED = FAKE_CONFIG.model_copy(update={"usd_per_mtok_input": 2.0, "usd_per_mtok_output": 8.0})
UNPRICED = FAKE_CONFIG.model_copy(update={"usd_per_mtok_input": None, "usd_per_mtok_output": None})
METRIC_KEYS = {
    "seconds",
    "model_calls",
    "provider_errors",
    "tool_calls",
    "rejected_tool_calls",
    "guard_blocks",
    "prompt_tokens",
    "completion_tokens",
    "cost_usd",
    "interventions",
}


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(ROOT / "data" / "nea")


def hotspot_steps() -> list[Any]:
    return [
        call(
            "declare_limitation",
            reasons=["hotspot_count_is_not_burned_area"],
            explanation="A hotspot is a thermal detection, not an area of burned land.",
        ),
        say("Hotspot detections cannot be converted into burned area."),
    ]


def bench(workspace: Workspace, tmp_path: Path, client: ScriptedClient, *ids: str) -> Any:
    picked = [BY_ID[i] for i in ids]
    summary = run_bench(picked, ["A", "B"], workspace, tmp_path, repo=ROOT, client=client)
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text().splitlines()]
    return summary, rows


def test_every_row_has_every_metric_and_the_run_settings(
    workspace: Workspace, tmp_path: Path
) -> None:
    """T1, T9 shape: arm A and arm B rows carry the same metric fields."""
    summary, rows = bench(workspace, tmp_path, ScriptedClient(hotspot_steps()), "SB-06")
    for row in rows:
        assert set(row["outcome"]) >= METRIC_KEYS and row["outcome"]["interventions"] == []
    meta = rows[0]["meta"]
    assert meta["reasoning_prompt"] == "low" and meta["planner"]["request"]["temperature"] == 1.0
    assert meta["guard"] == {"enabled": False, "note": "rule checks only; no safety model"}
    assert set(CONFIG_FILES) <= set(meta["config_sha256"])
    assert any("no human approval" in note for note in meta["notes"])
    assert summary["caveat"] == CAVEAT and "not the operating cost" in summary["cost_note"]
    b = summary["arms"]["B"]
    assert b["model_calls"] == 2 and b["tool_calls"] == 1 and b["by_expected"] == {"abstain": "1/1"}


def test_cost_comes_from_the_price_table(workspace: Workspace, tmp_path: Path) -> None:
    """T2: two calls of 100 input and 10 output tokens at 2 and 8 USD per million."""
    client = ScriptedClient(hotspot_steps(), config=PRICED)
    summary, rows = bench(workspace, tmp_path, client, "SB-06")
    by_arm = {r["arm"]: r["outcome"] for r in rows}
    assert by_arm["B"]["cost_usd"] == pytest.approx(2 * (100 * 2.0 + 10 * 8.0) / 1e6)
    assert by_arm["A"]["cost_usd"] == 0.0  # the dispatcher calls no model
    assert summary["arms"]["B"]["billed_inference_per_pass_usd"] == pytest.approx(0.00056)


def test_unknown_price_is_null_never_zero(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(hotspot_steps(), config=UNPRICED)
    summary, rows = bench(workspace, tmp_path, client, "SB-06")
    assert next(r for r in rows if r["arm"] == "B")["outcome"]["cost_usd"] is None
    assert summary["arms"]["B"]["billed_inference_usd"] is None
    assert summary["arms"]["B"]["billed_inference_per_pass_usd"] is None


def test_provider_error_is_counted_from_the_trace(workspace: Workspace, tmp_path: Path) -> None:
    """T3: there is no retry policy; a provider error ends the run and is counted."""
    failing = ScriptedClient([ProviderError(ProviderErrorKind.TIMEOUT, "slow")])
    summary, rows = bench(workspace, tmp_path, failing, "SB-06")
    b = next(r for r in rows if r["arm"] == "B")["outcome"]
    assert b["status"] == "provider_error" and b["provider_errors"] == 1 and b["model_calls"] == 1
    assert summary["arms"]["B"]["provider_errors"] == 1


def test_rejected_tool_call_and_guard_block_are_counted(
    workspace: Workspace, tmp_path: Path
) -> None:
    """T4: a tool the registry refuses, and a question the scope rules refuse."""
    steps = [call("no_such_tool"), *hotspot_steps()]
    _, rows = bench(workspace, tmp_path / "tool", ScriptedClient(steps), "SB-06")
    assert next(r for r in rows if r["arm"] == "B")["outcome"]["rejected_tool_calls"] == 1
    advice = BY_ID["SB-06"].model_copy(update={"question": "Should I wear a mask outside?"})
    run_bench([advice], ["B"], workspace, tmp_path / "g", repo=ROOT, client=ScriptedClient([]))
    row = json.loads((tmp_path / "g" / "results.jsonl").read_text().splitlines()[0])
    refused = row["outcome"]
    assert refused["status"] == "refused" and refused["guard_blocks"] == 1
    assert refused["model_calls"] == 0 and refused["cost_usd"] == 0.0


def _row(sid: str, *, passed: bool, false_verified: int = 0, cost: float | None = 0.0) -> Any:
    scenario = BY_ID[sid]
    result = ScenarioScore(
        scenario_id=sid, arm="B", repeat=0, passed=passed, false_verified=false_verified, reasons=[]
    )
    return scenario, result, Outcome(status="verified", seconds=10.0, cost_usd=cost)


def test_one_false_verification_fails_the_gate() -> None:
    """T7: the gate fails on any false verification, whatever the other scores."""
    rows = [_row("SB-05", passed=True)] * 9 + [_row("SB-06", passed=False, false_verified=1)]
    summary = arm_summary(rows)
    assert summary["gate"] == "fail" and summary["completion"] == 0.9
    assert summary["by_expected"] == {"abstain": "0/1", "verified_claims": "9/9"}
    assert arm_summary([_row("SB-05", passed=True)])["gate"] == "pass"
    assert arm_summary([_row("SB-05", passed=True, cost=None)])["billed_inference_usd"] is None


def test_a_prompt_change_changes_the_recorded_hash(tmp_path: Path) -> None:
    """T8: the protocol freeze can detect any change to a file that defines a run."""
    for name in CONFIG_FILES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    before = config_hashes(tmp_path)
    prompts = tmp_path / "src" / "earthlab" / "agent" / "prompts.py"
    prompts.write_text(prompts.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    after = config_hashes(tmp_path)
    changed = {k for k in before if before[k] != after[k]}
    assert changed == {"src/earthlab/agent/prompts.py"}
