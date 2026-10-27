"""Regression tests: every limit is checked before each model call and each tool call."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import FAKE_CONFIG, ScriptedClient, call, say

from earthlab.agent.budget import Budget, BudgetMeter, BudgetStop
from earthlab.agent.findings import FindingsLedger
from earthlab.agent.loop import Investigator, RunStatus
from earthlab.llm.types import Usage
from earthlab.metrics import EarthlabMetrics
from earthlab.runtime import Workspace, build_registry, investigate, new_run_dir, open_workspace
from earthlab.trace import RunTrace

HAZE = {"start": "2015-09-01T00:00", "end": "2015-11-01T00:00"}
PEAK = {**HAZE, "kind": "peak_region", "region": "west", "value": 471, "statement": "Seen."}
HOSTED = FAKE_CONFIG.model_copy(
    update={
        "name": "fake-hosted",
        "kind": "hosted",
        "base_url": "https://example.invalid/v1",
        "usd_per_mtok_input": None,
        "usd_per_mtok_output": None,
    }
)
PRICED = HOSTED.model_copy(update={"usd_per_mtok_input": 1.0, "usd_per_mtok_output": 4.0})


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def batch(*calls: tuple[str, dict[str, Any]]) -> Any:
    return ("", list(calls))


def coverage() -> tuple[str, dict[str, Any]]:
    return ("inspect_coverage", dict(HAZE))


def trace_events(run_dir: Path, event: str) -> int:
    return (run_dir / "trace.jsonl").read_text(encoding="utf-8").count(f'"event": "{event}"')


def test_a_batch_stops_exactly_at_the_tool_call_limit(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([batch(*[coverage()] * 6)])
    run_dir = new_run_dir(tmp_path)
    result = investigate("q", client, workspace, run_dir, budget=Budget(max_tool_calls=2))
    assert result.tool_calls == 2 and result.skipped_tool_calls == 4
    assert result.status is RunStatus.BUDGET_EXHAUSTED and "tool-call limit 2" in result.stop_reason
    assert trace_events(run_dir, "tool_skipped") == 4
    assert trace_events(run_dir, "tool_result") == 2 and len(client.requests) == 1


def test_a_batch_at_the_limit_runs_every_call(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([batch(coverage(), coverage())])
    budget = Budget(max_tool_calls=2, max_turns=1)
    result = investigate("q", client, workspace, new_run_dir(tmp_path), budget=budget)
    assert result.tool_calls == 2 and result.skipped_tool_calls == 0


def test_only_executed_submissions_count(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            call("submit_findings", claims=[{"kind": "nonsense"}]),
            call("submit_findings", claims=[PEAK]),
            say("West had the highest value (R1.1)."),
        ]
    )
    budget = Budget(max_submissions=1)
    result = investigate("q", client, workspace, new_run_dir(tmp_path), budget=budget)
    assert result.submissions == 1 and result.status is RunStatus.VERIFIED


def test_a_second_submission_in_one_batch_is_skipped(workspace: Workspace, tmp_path: Path) -> None:
    wrong = {**PEAK, "region": "east"}
    submit = ("submit_findings", {"claims": [wrong]})
    client = ScriptedClient([batch(submit, submit), say("East was not the peak.")])
    budget = Budget(max_submissions=1)
    result = investigate("q", client, workspace, new_run_dir(tmp_path), budget=budget)
    assert result.submissions == 1 and result.skipped_tool_calls == 1
    assert len(result.ledger.rounds) == 1


def test_hosted_provider_without_a_price_is_refused(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([say("never sent")], config=HOSTED)
    result = investigate("q", client, workspace, new_run_dir(tmp_path))
    assert client.requests == [] and result.turns == 0
    assert result.status is RunStatus.BUDGET_EXHAUSTED and "no price" in result.stop_reason


def test_a_call_that_could_cross_the_cost_cap_is_not_sent(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient([say("never sent")], config=PRICED)
    budget = Budget(max_usd=0.01, max_output_tokens=4096)  # reply alone could cost 0.016
    result = investigate("q", client, workspace, new_run_dir(tmp_path), budget=budget)
    assert client.requests == [] and "could cost" in result.stop_reason


def test_missing_usage_on_a_billed_provider_charges_the_worst_case() -> None:
    meter = BudgetMeter(Budget(max_output_tokens=1000))
    worst = meter.reserve_model_call(PRICED, request_bytes=2000)
    assert worst == pytest.approx((2000 * 1.0 + 1000 * 4.0) / 1e6)
    assert meter.settle_model_call(PRICED, Usage(), worst) == worst
    reported = meter.settle_model_call(
        PRICED, Usage(prompt_tokens=100, completion_tokens=10), worst
    )
    assert reported == pytest.approx(140 / 1e6) and meter.turns == 1


def test_local_provider_without_a_price_is_not_billed() -> None:
    local = FAKE_CONFIG.model_copy(update={"usd_per_mtok_input": None})
    assert BudgetMeter(Budget()).worst_case_usd(local, 10_000) == 0.0


def test_time_limit_is_checked_before_each_tool_call(workspace: Workspace, tmp_path: Path) -> None:
    """The clock jumps past the limit when the first tool runs; the rest are skipped."""
    now = [0.0]
    ledger = FindingsLedger()
    registry = build_registry(workspace, ledger)
    execute = registry.execute

    def slow_execute(name: str, arguments: str) -> Any:
        now[0] = 99.0
        return execute(name, arguments)

    registry.execute = slow_execute  # type: ignore[method-assign,assignment]
    client = ScriptedClient([batch(coverage(), coverage(), coverage())])
    investigator = Investigator(
        client,
        registry,
        ledger,
        metrics=EarthlabMetrics(),
        trace=RunTrace(tmp_path / "trace.jsonl"),
        budget=Budget(max_seconds=10),
        clock=lambda: now[0],
    )
    result = investigator.run("q")
    assert result.tool_calls == 1 and result.skipped_tool_calls == 2
    assert "time limit" in result.stop_reason


def test_each_request_timeout_is_capped_by_the_time_left(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient([say("text")])
    budget = Budget(max_seconds=30)
    investigate("q", client, workspace, new_run_dir(tmp_path), budget=budget)
    timeout = client.requests[0]["timeout"]
    assert timeout is not None and 0 < timeout <= 30


def test_meter_refuses_on_turns_time_and_spent_cost() -> None:
    meter = BudgetMeter(Budget(max_turns=1, max_seconds=5, max_usd=0.5), clock=lambda: 0.0)
    meter.reserve_model_call(FAKE_CONFIG, 10)
    with pytest.raises(BudgetStop, match="turn limit 1"):
        meter.reserve_model_call(FAKE_CONFIG, 10)
    late = [0.0]
    timed = BudgetMeter(Budget(max_seconds=5), clock=lambda: late[0])
    late[0] = 6.0
    with pytest.raises(BudgetStop, match="time limit"):
        timed.reserve_model_call(FAKE_CONFIG, 10)
    meter.cost_usd = 0.6
    assert meter.exhausted() == "turn limit 1 reached"
    spent = BudgetMeter(Budget(max_usd=0.5))
    spent.cost_usd = 0.6
    assert spent.exhausted() == "estimated cost above 0.5 USD"


def test_revision_is_not_run_when_its_reservation_fails(
    workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reserve = BudgetMeter.reserve_model_call
    calls = [0]

    def third_call_refused(self: BudgetMeter, config: Any, request_bytes: int) -> float:
        calls[0] += 1
        if calls[0] == 3:
            raise BudgetStop("next model call could cost too much")
        return reserve(self, config, request_bytes)

    monkeypatch.setattr(BudgetMeter, "reserve_model_call", third_call_refused)
    client = ScriptedClient([call("submit_findings", claims=[PEAK]), say("West 471.")])
    result = investigate("q", client, workspace, new_run_dir(tmp_path))
    assert len(client.requests) == 2 and result.status is RunStatus.ANSWER_UNVERIFIED
    assert result.answer_issues[-1] == "revision not run: next model call could cost too much"
