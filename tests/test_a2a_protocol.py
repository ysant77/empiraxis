"""The adapter over a real local socket, driven by the official SDK client and a fake port."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("a2a")

import httpx
from a2a.client import A2ACardResolver, A2AClientError, Client
from a2a.helpers.proto_helpers import get_data_parts, new_text_part
from a2a.types.a2a_pb2 import AgentCard, CancelTaskRequest, Message, Role, Task, TaskState
from a2a.utils.errors import A2AError, InvalidParamsError, TaskNotCancelableError, TaskNotFoundError
from conftest import REPO_DATA
from test_a2a_support import (
    CASE,
    NO_SCOPE_TOKEN,
    OTHER_TOKEN,
    TOKEN,
    FakeEngineer,
    LiveAgent,
    live_agent,
    payload,
    typed_message,
    wait_for,
)

from earthlab.a2a.contracts import REFUSAL_MEDIA_TYPE, REPORT_MEDIA_TYPE, REQUEST_MEDIA_TYPE
from earthlab.a2a.engineer import EngineerPort
from earthlab.a2a.ledger import Quota
from earthlab.agent.budget import Budget
from earthlab.cases.tools import CaseLibrary
from earthlab.runtime import open_workspace
from earthlab.trace import RunTrace

REPORT_FIELDS = {
    "schema_version", "status_label", "a2a_task_id", "context_id", "request_id", "trace_id",
    "request_sha256", "engineering_task_id", "engineering_task_sha256", "status",
    "verified_finding_ids", "limitation_reasons", "plan_sha256", "critic_verdicts",
    "source_sha256", "result_sha256", "trace_head_sha256", "provider", "model",
    "served_model", "elapsed_ms",
}  # fmt: skip


@pytest.fixture(scope="module")
def cases() -> CaseLibrary:
    library = open_workspace(REPO_DATA).cases
    assert library is not None
    return library


def report_of(task: Task) -> dict[str, Any]:
    [artifact] = task.artifacts
    [part] = artifact.parts
    assert part.media_type == REPORT_MEDIA_TYPE
    [data] = get_data_parts([part])
    assert isinstance(data, dict)
    return data


def refusal_of(task: Task) -> dict[str, Any]:
    assert task.status.state == TaskState.TASK_STATE_REJECTED
    assert not task.artifacts
    [part] = task.status.message.parts
    assert part.media_type == REFUSAL_MEDIA_TYPE
    [data] = get_data_parts([part])
    assert isinstance(data, dict)
    return data


def events(agent: LiveAgent, task_id: str) -> list[str]:
    trace = RunTrace(agent.runs_root / task_id / "a2a_trace.jsonl")
    trace.verify()
    return [entry["event"] for entry in trace.records()]


def serve(engineer: EngineerPort, cases: CaseLibrary, tmp_path: Path, **kw: Any) -> Any:
    return live_agent(engineer, cases, tmp_path, **kw)


def test_the_official_client_reads_the_card_from_the_well_known_path(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    async def card(url: str) -> AgentCard:
        async with httpx.AsyncClient() as http:
            return await A2ACardResolver(http, url).get_agent_card()

    with serve(FakeEngineer(), cases, tmp_path) as agent:
        found = asyncio.run(card(agent.url))
        raw = httpx.get(f"{agent.url}/.well-known/agent-card.json").json()
    assert "experimental" in found.name.lower()
    assert "no claim of A2A conformance" in found.description
    [interface] = found.supported_interfaces
    assert (interface.protocol_binding, interface.protocol_version) == ("JSONRPC", "1.0")
    assert interface.url == f"{agent.url}/a2a"
    assert not found.capabilities.streaming and not found.capabilities.push_notifications
    assert [s.id for s in found.skills] == ["bounded-geospatial-investigation"]
    assert found.default_input_modes == [REQUEST_MEDIA_TYPE]
    assert found.security_schemes["bearer"].http_auth_security_scheme.scheme == "Bearer"
    assert CASE not in json.dumps(raw) and "provider" not in json.dumps(raw).lower()


def test_send_runs_one_task_and_the_final_artifact_is_digests_and_ids_only(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer()
    with serve(engineer, cases, tmp_path) as agent:
        task = agent.send(payload())
        again = agent.get(task.id)
    assert task.status.state == TaskState.TASK_STATE_COMPLETED
    assert again.status.state == TaskState.TASK_STATE_COMPLETED
    report = report_of(task)
    assert set(report) == REPORT_FIELDS
    assert report["status_label"] == "experimental"
    assert report["verified_finding_ids"] == ["A1.1"]
    assert report["a2a_task_id"] == task.id
    assert report["context_id"] == task.context_id
    assert report["engineering_task_id"] == "req-1.ge"
    assert len(task.artifacts[0].SerializeToString()) < 4096
    assert all(not p.raw and not p.url for a in task.artifacts for p in a.parts)


def test_the_task_comes_from_the_case_and_not_from_the_peer(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer()
    with serve(engineer, cases, tmp_path) as agent:
        agent.send(payload(requested_tools=["burned_area_summary"]))
    [job] = engineer.jobs
    assert job.task.case_id == CASE
    assert job.task.allowed_dataset_ids == tuple(sorted(cases.get(CASE).assets))
    assert "burned_area_summary" in job.task.allowed_tool_names
    assert "submit_plan" in job.task.allowed_tool_names  # the case grants it, not the peer
    assert "daily_peaks" not in job.task.allowed_tool_names
    assert job.task.approval_scope == "read-only pinned files"
    assert job.peer == "alpha"
    assert job.brief.author.provider == "a2a-peer"


def test_polling_shows_submitted_or_working_before_the_terminal_state(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer(hold=True)
    with serve(engineer, cases, tmp_path) as agent:
        task = agent.send(payload(), polling=True)
        assert task.status.state in (
            TaskState.TASK_STATE_SUBMITTED,
            TaskState.TASK_STATE_WORKING,
        )
        assert engineer.started.wait(5)
        assert agent.get(task.id).status.state == TaskState.TASK_STATE_WORKING
        engineer.release.set()
        wait_for(lambda: agent.get(task.id).status.state == TaskState.TASK_STATE_COMPLETED)
        assert events(agent, task.id)[0] == "a2a_received"


@pytest.mark.parametrize(
    ("data", "named"),
    [
        (payload(api_key="sk-injected"), "api_key"),
        (payload(trace_id="short"), "trace_id"),
        (payload(request_id="UPPER CASE"), "request_id"),
        (payload(budget={"max_turns": 0}), "budget.max_turns"),
        (payload(intent="not-an-intent"), "intent"),
        ({"question": "too few fields"}, "case_id"),
    ],
)
def test_a_malformed_request_is_a_protocol_error_and_starts_nothing(
    cases: CaseLibrary, tmp_path: Path, data: dict[str, Any], named: str
) -> None:
    engineer = FakeEngineer()
    with serve(engineer, cases, tmp_path) as agent, pytest.raises(InvalidParamsError) as caught:
        agent.send(data)
    assert named in str(caught.value)
    assert "sk-injected" not in str(caught.value)
    assert engineer.jobs == []


@pytest.mark.parametrize(
    "message",
    [
        Message(message_id="m", role=Role.ROLE_USER, parts=[new_text_part("run the haze case")]),
        typed_message(payload(), media_type="application/json"),
        Message(
            message_id="m",
            role=Role.ROLE_USER,
            task_id="some-task",
            parts=typed_message(payload()).parts,
        ),
    ],
    ids=["free-text", "wrong-media-type", "follow-up"],
)
def test_only_one_typed_part_in_a_new_task_is_accepted(
    cases: CaseLibrary, tmp_path: Path, message: Message
) -> None:
    engineer = FakeEngineer()
    with serve(engineer, cases, tmp_path) as agent, pytest.raises(InvalidParamsError):
        agent.send_message(message)
    assert engineer.jobs == []


def test_bad_bytes_and_a_missing_version_get_protocol_errors(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer()
    get = {"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "x"}}
    with serve(engineer, cases, tmp_path) as agent:
        assert agent.rpc(b"{not json").json()["error"]["code"] == -32700
        unversioned = agent.rpc(json.dumps(get).encode(), version=None).json()
        assert unversioned["error"]["code"] == -32009
        assert agent.rpc(b"x" * 70_000).status_code == 413
    assert engineer.jobs == []


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"case_id": "not-a-case"}, "unknown_case"),
        ({"requested_tools": ["daily_peaks"]}, "tool_out_of_scope"),
        ({"requested_tools": ["run_shell"]}, "tool_out_of_scope"),
        ({"requested_datasets": ["nea-pm25-2015"]}, "dataset_out_of_scope"),
        ({"budget": {"max_turns": 13}}, "budget_above_limit"),
        ({"budget": {"max_usd": 2.0}}, "budget_above_limit"),
        ({"period_start": "2016-01-01T00:00:00Z"}, "brief_invalid"),
        ({"constraints": ["stay under 123456 hectares"]}, "brief_invalid"),
    ],
)
def test_a_request_outside_the_scope_is_rejected_and_the_engineer_never_runs(
    cases: CaseLibrary, tmp_path: Path, overrides: dict[str, Any], code: str
) -> None:
    engineer = FakeEngineer()
    with serve(engineer, cases, tmp_path) as agent:
        task = agent.send(payload(**overrides))
        recorded = events(agent, task.id)
        wait_for(lambda: agent.send(payload(request_id="next")).id != task.id)
    assert refusal_of(task)["code"] == code
    assert recorded == ["a2a_received", "a2a_refused"]
    assert len(engineer.jobs) == 1  # only the follow-up request, which is in scope


def test_a_peer_can_lower_the_budget_and_the_job_carries_the_lower_value(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer()
    wanted = {"max_turns": 3, "max_tool_calls": 4, "max_seconds": 30.0, "max_usd": 0.0}
    with serve(engineer, cases, tmp_path) as agent:
        agent.send(payload(budget=wanted))
    [job] = engineer.jobs
    assert (job.budget.max_turns, job.budget.max_tool_calls) == (3, 4)
    assert (job.budget.max_seconds, job.budget.max_usd) == (30.0, 0.0)
    assert (job.task.max_model_calls, job.task.max_tool_calls) == (3, 4)


def test_the_running_quota_refuses_a_second_task_until_the_first_stops(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer(hold=True)
    with serve(engineer, cases, tmp_path, quota=Quota(max_running=1)) as agent:
        first = agent.send(payload(), polling=True)
        with pytest.raises(A2AError, match="quota_exhausted"):
            agent.send(payload(request_id="req-2"), polling=True)
        engineer.release.set()
        wait_for(lambda: agent.get(first.id).status.state == TaskState.TASK_STATE_COMPLETED)
        wait_for(lambda: "a2a_worker_stopped" in events(agent, first.id))
        second = agent.send(payload(request_id="req-2"))  # the refused ID stays free
    assert second.status.state == TaskState.TASK_STATE_COMPLETED


def test_the_task_allowance_is_per_peer_and_is_not_refunded(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer()
    with serve(engineer, cases, tmp_path, quota=Quota(max_running=1, max_tasks=1)) as agent:
        agent.send(payload())
        wait_for(lambda: len(engineer.jobs) == 1)
        with pytest.raises(A2AError, match="quota_exhausted"):
            agent.send(payload(request_id="req-2"))
        beta = agent.send(payload(request_id="req-2"), token=OTHER_TOKEN)
    assert beta.status.state == TaskState.TASK_STATE_COMPLETED


def test_the_server_limit_passes_to_the_job_when_the_peer_asks_for_nothing(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer()
    with serve(engineer, cases, tmp_path, limit=Budget(max_turns=2, max_usd=0.0)) as agent:
        over = agent.send(payload(budget={"max_turns": 3}))
        agent.send(payload(request_id="req-2"))
    assert refusal_of(over)["code"] == "budget_above_limit"
    [job] = engineer.jobs
    assert (job.budget.max_turns, job.budget.max_usd) == (2, 0.0)


def test_a_duplicate_request_returns_the_same_task_and_runs_once(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer()
    with serve(engineer, cases, tmp_path) as agent:
        first = agent.send(payload())
        again = agent.send(payload())
    assert again.id == first.id
    assert again.context_id == first.context_id
    assert report_of(again) == report_of(first)
    assert len(engineer.jobs) == 1


def test_a_duplicate_during_the_run_returns_the_running_task(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer(hold=True)
    with serve(engineer, cases, tmp_path) as agent:
        first = agent.send(payload(), polling=True)
        assert engineer.started.wait(5)
        again = agent.send(payload())
        assert again.id == first.id
        assert again.status.state == TaskState.TASK_STATE_WORKING
        engineer.release.set()
    assert len(engineer.jobs) == 1


def test_a_reused_request_id_with_other_content_is_refused(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer()
    with serve(engineer, cases, tmp_path) as agent:
        agent.send(payload())
        with pytest.raises(InvalidParamsError, match="already used"):
            agent.send(payload(constraints=["another request"]))
    assert len(engineer.jobs) == 1


def test_two_peers_can_use_one_request_id_without_sharing_a_task(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer()
    with serve(engineer, cases, tmp_path) as agent:
        alpha = agent.send(payload())
        beta = agent.send(payload(), token=OTHER_TOKEN)
    assert alpha.id != beta.id
    assert [job.peer for job in engineer.jobs] == ["alpha", "beta"]


def test_a_lost_connection_does_not_stop_the_task_and_the_retry_recovers_it(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer(hold=True)
    with serve(engineer, cases, tmp_path) as agent:
        with pytest.raises(A2AClientError):
            agent.send(payload(), timeout=0.3)  # the client drops the blocking call
        assert engineer.started.wait(5)
        engineer.release.set()
        wait_for(lambda: agent.send(payload()).status.state == TaskState.TASK_STATE_COMPLETED)
        recovered = agent.send(payload())
    assert len(engineer.jobs) == 1
    assert report_of(recovered)["verified_finding_ids"] == ["A1.1"]


def test_cancel_stops_the_worker_and_holds_the_slot_until_it_stops(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer(hold=True)

    async def cancel(client: Client) -> Task:
        return await client.cancel_task(CancelTaskRequest(id=task.id))

    with serve(engineer, cases, tmp_path, quota=Quota(max_running=1)) as agent:
        task = agent.send(payload(), polling=True)
        assert engineer.started.wait(5)
        cancelled = agent.call(cancel)
        assert cancelled.status.state == TaskState.TASK_STATE_CANCELED
        assert engineer.saw_cancel.wait(5)
        wait_for(lambda: "a2a_worker_stopped" in events(agent, task.id))
        assert agent.get(task.id).status.state == TaskState.TASK_STATE_CANCELED
        assert not agent.get(task.id).artifacts
        with pytest.raises(TaskNotCancelableError):
            agent.call(cancel)
        engineer.release.set()
        after = agent.send(payload(request_id="req-2"))
    assert after.status.state == TaskState.TASK_STATE_COMPLETED
    assert "a2a_cancel_requested" in events(agent, task.id)


def test_cancel_of_a_finished_or_unknown_task_is_an_error(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    async def cancel(client: Client, task_id: str) -> Task:
        return await client.cancel_task(CancelTaskRequest(id=task_id))

    with serve(FakeEngineer(), cases, tmp_path) as agent:
        done = agent.send(payload())
        with pytest.raises(TaskNotCancelableError):
            agent.call(lambda c: cancel(c, done.id))
        with pytest.raises(TaskNotFoundError):
            agent.call(lambda c: cancel(c, "no-such-task"))


def test_an_engineer_fault_fails_the_task_without_leaking_its_text(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    engineer = FakeEngineer(fault=RuntimeError("secret path /home/x"))
    with serve(engineer, cases, tmp_path, quota=Quota(max_running=1)) as agent:
        task = agent.send(payload())
        wait_for(lambda: "a2a_worker_stopped" in events(agent, task.id))
        assert "a2a_fault" in events(agent, task.id)
    assert task.status.state == TaskState.TASK_STATE_FAILED
    assert "secret" not in str(task)
    assert not task.artifacts


@pytest.mark.parametrize(
    ("token", "status"), [(None, 401), ("wrong-token", 401), (NO_SCOPE_TOKEN, 403)]
)
def test_the_rpc_path_needs_a_token_with_the_run_scope(
    cases: CaseLibrary, tmp_path: Path, token: str | None, status: int
) -> None:
    engineer = FakeEngineer()
    with serve(engineer, cases, tmp_path) as agent:
        with pytest.raises(A2AClientError):
            agent.send(payload(), token=token)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        answer = httpx.post(f"{agent.url}/a2a", content=b"{}", headers=headers)
    assert answer.status_code == status
    assert engineer.jobs == []


def test_one_peer_cannot_read_or_cancel_the_task_of_another(
    cases: CaseLibrary, tmp_path: Path
) -> None:
    async def cancel(client: Client) -> Task:
        return await client.cancel_task(CancelTaskRequest(id=task.id))

    with serve(FakeEngineer(hold=True), cases, tmp_path) as agent:
        task = agent.send(payload(), polling=True)
        with pytest.raises(TaskNotFoundError):
            agent.get(task.id, token=OTHER_TOKEN)
        with pytest.raises(TaskNotFoundError):
            agent.call(cancel, token=OTHER_TOKEN)
        assert agent.get(task.id).status.state != TaskState.TASK_STATE_CANCELED
        agent.call(cancel)


def test_no_token_reaches_a_saved_record(cases: CaseLibrary, tmp_path: Path) -> None:
    with serve(FakeEngineer(), cases, tmp_path) as agent:
        task = agent.send(payload())
    saved = (tmp_path / task.id / "a2a_trace.jsonl").read_text()
    assert TOKEN not in saved
    assert "Bearer" not in saved
