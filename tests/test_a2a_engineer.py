"""The adapter on the real engineer path: `investigate`, with a scripted model client.

These tests show that the budget, the scope, the guard and the verifier still decide the
run when a request arrives over A2A. No model server runs.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("a2a")

from a2a.client import Client
from a2a.helpers.proto_helpers import get_data_parts
from a2a.types.a2a_pb2 import CancelTaskRequest, Task, TaskState
from conftest import REPO_DATA
from fake_client import FAKE_CONFIG, ScriptedClient, Step, call, say
from test_a2a_support import CASE, TRACE_ID, live_agent, payload, typed_message, wait_for
from workflow_helpers import assignment

from earthlab.a2a.admission import bounded_budget
from earthlab.a2a.contracts import RefusalV1, RequestedBudget
from earthlab.a2a.engineer import CANCEL_REASON, InvestigatorEngineer
from earthlab.a2a.executor import task_state
from earthlab.a2a.handler import parse_request
from earthlab.a2a.ledger import Quota, QuotaExhausted, RequestConflict, RequestLedger
from earthlab.agent.budget import Budget
from earthlab.digest import file_digest
from earthlab.implement.bindings import BindingRefused
from earthlab.llm.providers import ProviderConfig
from earthlab.runtime import Workspace, open_workspace
from earthlab.trace import RunTrace
from earthlab.verify.replay import replay_run
from earthlab.workflow.contracts import WorkflowStatus

MCD = "mcd64a1-061-kalimantan-2015"
FIRMS = "firms-modis-sp-kalimantan-2015"
SEPT_HA = 77426.0


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def plan() -> dict[str, Any]:
    return {
        "case_id": CASE,
        "requested_intent": "observational_summary",
        "research_intent": "observational_summary",
        "target": "burned_area",
        "period_start": "2015-09-01T00:00:00Z",
        "period_end": "2015-10-01T00:00:00Z",
        "datasets": [
            {"dataset_id": MCD, "used_as": "burned_area"},
            {"dataset_id": FIRMS, "used_as": "active_fire", "role": "context"},
        ],
        "method_id": "mcd64a1_burned_area",
        "rationale": "MCD64A1 maps burned area; FIRMS is context only.",
    }


def claim() -> dict[str, Any]:
    return {
        "case_id": CASE,
        "month": "2015-09",
        "quantity": "burned_area_ha",
        "value": SEPT_HA,
        "statement": "Mapped burned area after quality checks.",
    }


def verified_steps() -> list[Step]:
    return [
        call("submit_plan", **plan()),
        call("burned_area_summary", case_id=CASE, month="2015-09"),
        call("submit_area_findings", claims=[claim()]),
        say("The mapped burned area for the study box is in A1.1; it is not forest loss."),
    ]


def serve(client: ScriptedClient, workspace: Workspace, root: Path) -> Any:
    assert workspace.cases is not None
    engineer = InvestigatorEngineer(client, workspace, assignment(client))
    return live_agent(engineer, workspace.cases, root)


def report_of(task: Task) -> dict[str, Any]:
    [data] = get_data_parts(task.artifacts[0].parts)
    assert isinstance(data, dict)
    return data


def run_records(root: Path, task: Task) -> list[dict[str, Any]]:
    trace = RunTrace(root / task.id / "trace.jsonl")
    trace.verify()
    return list(trace.records())


def test_a_verified_run_returns_ids_and_digests_that_match_the_saved_run(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(verified_steps())
    with serve(client, workspace, tmp_path) as agent:
        task = agent.send(payload())
    assert task.status.state == TaskState.TASK_STATE_COMPLETED
    report = report_of(task)
    assert report["status"] == "verified"
    assert report["verified_finding_ids"] == ["A1.1"]
    assert report["critic_verdicts"] == ["accept"]
    run_dir = tmp_path / task.id
    assert report["result_sha256"] == file_digest(run_dir / "result.json")
    assert report["trace_head_sha256"] == run_records(tmp_path, task)[-1]["hash"]
    assert report["source_sha256"] == [workspace.snapshot.sha256]
    assert report["served_model"] == "muse-glimmer-30B"
    assert str(SEPT_HA) not in json.dumps(report) and "77426" not in json.dumps(report)


def test_the_saved_run_replays_offline_and_carries_the_peer_trace_id(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(verified_steps())
    with serve(client, workspace, tmp_path) as agent:
        task = agent.send(payload())
    replayed = replay_run(tmp_path / task.id, workspace)
    assert replayed.ok, replayed.problems
    assert replayed.area == [1, 1]
    handoff = run_records(tmp_path, task)[0]
    assert handoff["event"] == "task_handoff"
    assert handoff["data"]["a2a"] == {
        "task_id": task.id, "context_id": task.context_id, "peer": "alpha", "trace_id": TRACE_ID,
    }  # fmt: skip
    adapter = RunTrace(tmp_path / task.id / "a2a_trace.jsonl")
    assert adapter.verify() >= 3
    assert next(adapter.records())["data"]["trace_id"] == TRACE_ID


def test_the_model_sees_only_the_case_tools_and_a_tool_outside_them_never_runs(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            call("submit_plan", **plan()),
            call("daily_peaks", start="2015-09-01", end="2015-09-02"),
            say("Nothing is verified."),
        ]
    )
    with serve(client, workspace, tmp_path) as agent:
        task = agent.send(payload())
    offered = {tool["function"]["name"] for tool in client.requests[0]["tools"]}
    assert "daily_peaks" not in offered
    assert "burned_area_summary" in offered
    results = [e["data"] for e in run_records(tmp_path, task) if e["event"] == "tool_result"]
    assert [r["outcome"] for r in results if r["name"] == "daily_peaks"] == ["rejected"]
    assert report_of(task)["verified_finding_ids"] == []


def test_a_run_that_spends_its_budget_fails_with_a_typed_report(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(verified_steps())
    with serve(client, workspace, tmp_path) as agent:
        task = agent.send(payload(budget={"max_turns": 1}))
    assert task.status.state == TaskState.TASK_STATE_FAILED
    assert report_of(task)["status"] == "budget_exhausted"
    assert len(client.requests) == 1


def test_the_safety_gate_still_refuses_a_forecast_before_any_model_call(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient([])
    question = "Forecast the burned area in the Kalimantan study box for next year."
    with serve(client, workspace, tmp_path) as agent:
        task = agent.send(payload(question=question))
    assert client.requests == []
    assert task.status.state == TaskState.TASK_STATE_REJECTED
    assert report_of(task)["status"] == "refused"


def test_a_cancel_ends_the_real_run_before_its_next_model_call(
    workspace: Workspace, tmp_path: Path
) -> None:
    entered, resume = threading.Event(), threading.Event()

    class Gated(ScriptedClient):
        def chat(self, *args: Any, **kwargs: Any) -> Any:
            answer = super().chat(*args, **kwargs)
            entered.set()
            assert resume.wait(10)
            return answer

    client = Gated(verified_steps())

    async def cancel(sdk: Client) -> Task:
        return await sdk.cancel_task(CancelTaskRequest(id=task.id))

    with serve(client, workspace, tmp_path) as agent:
        task = agent.send(payload(), polling=True)
        assert entered.wait(5)
        assert agent.call(cancel).status.state == TaskState.TASK_STATE_CANCELED
        resume.set()
        log = RunTrace(tmp_path / task.id / "a2a_trace.jsonl")
        wait_for(lambda: any(e["event"] == "a2a_worker_stopped" for e in log.records()))
        assert agent.get(task.id).status.state == TaskState.TASK_STATE_CANCELED
    assert len(client.requests) == 1
    saved = json.loads((tmp_path / task.id / "result.json").read_text())
    assert saved["status"] == "provider_error"
    assert CANCEL_REASON in saved["stop_reason"]


def test_a_client_that_is_not_the_bound_engineer_is_refused(workspace: Workspace) -> None:
    bound = ScriptedClient([])
    other = FAKE_CONFIG.model_copy(update={"model": "another-model"})
    assert isinstance(other, ProviderConfig)
    with pytest.raises(BindingRefused):
        InvestigatorEngineer(ScriptedClient([], other), workspace, assignment(bound))


@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("verified", TaskState.TASK_STATE_COMPLETED),
        ("partial", TaskState.TASK_STATE_COMPLETED),
        ("abstained", TaskState.TASK_STATE_COMPLETED),
        ("no_supported_findings", TaskState.TASK_STATE_COMPLETED),
        ("answer_unverified", TaskState.TASK_STATE_COMPLETED),
        ("budget_exhausted", TaskState.TASK_STATE_FAILED),
        ("provider_error", TaskState.TASK_STATE_FAILED),
        ("failed", TaskState.TASK_STATE_FAILED),
        ("refused", TaskState.TASK_STATE_REJECTED),
    ],
)
def test_each_run_status_has_one_task_state(status: WorkflowStatus, state: int) -> None:
    assert task_state(status) == state


def test_the_budget_rule_keeps_the_server_value_for_a_field_left_out() -> None:
    bounded = bounded_budget(RequestedBudget(max_turns=2), Budget(max_turns=5, max_tool_calls=7))
    assert isinstance(bounded, Budget)
    assert (bounded.max_turns, bounded.max_tool_calls) == (2, 7)
    refused = bounded_budget(RequestedBudget(max_seconds=99.0), Budget(max_seconds=10.0))
    assert isinstance(refused, RefusalV1)
    assert refused.code == "budget_above_limit"


def test_the_ledger_keeps_keys_per_peer_and_slots_until_release() -> None:
    ledger = RequestLedger(Quota(max_running=1, max_tasks=2))
    ticket, new = ledger.claim("a", "r", "d1", "ctx")
    assert new and ticket.context_id == "ctx"
    assert ledger.claim("a", "r", "d1", None) == (ticket, False)
    with pytest.raises(RequestConflict):
        ledger.claim("a", "r", "d2", None)
    with pytest.raises(QuotaExhausted):
        ledger.claim("a", "r2", "d", None)
    assert ledger.running("a") == 1
    ledger.release("a")
    ledger.claim("a", "r2", "d", None)
    ledger.release("a")
    with pytest.raises(QuotaExhausted):
        ledger.claim("a", "r3", "d", None)


def test_the_request_parser_accepts_the_typed_part() -> None:
    assert parse_request(typed_message(payload())).request_id == "req-1"
