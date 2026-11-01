"""Shared parts of the A2A tests: a real local server, the official client and a fake port.

The server runs under uvicorn on a 127.0.0.1 socket in a thread. Every test talks to it
through the SDK client over that socket, except the tests that send deliberately bad bytes.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import pytest

pytest.importorskip("a2a")

import httpx
import uvicorn
from a2a.client import Client, ClientConfig, create_client
from a2a.helpers.proto_helpers import new_data_part
from a2a.types.a2a_pb2 import (
    GetTaskRequest,
    Message,
    Role,
    SendMessageRequest,
    Task,
)
from a2a.utils.constants import VERSION_HEADER

from earthlab.a2a.admission import EngineerJob
from earthlab.a2a.app import AgentSettings, build_app
from earthlab.a2a.auth import Peer, PeerRegistry, token_digest
from earthlab.a2a.contracts import REQUEST_MEDIA_TYPE
from earthlab.a2a.engineer import EngineerOutcome, EngineerPort
from earthlab.a2a.ledger import Quota
from earthlab.agent.budget import Budget
from earthlab.cases.tools import CaseLibrary
from earthlab.workflow.contracts import EngineeringReplyV1, RoleCall

TOKEN = "test-token-alpha"
OTHER_TOKEN = "test-token-beta"
NO_SCOPE_TOKEN = "test-token-gamma"
PEERS = PeerRegistry(
    [
        Peer("alpha", token_digest(TOKEN)),
        Peer("beta", token_digest(OTHER_TOKEN)),
        Peer("gamma", token_digest(NO_SCOPE_TOKEN), frozenset()),
    ]
)
CASE = "kalimantan-2015-burned-area"
QUESTION = "How much area burned in the Kalimantan study box in September 2015?"
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
DIGEST = "a" * 64
T = TypeVar("T")


def payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "request_id": "req-1",
        "trace_id": TRACE_ID,
        "question": QUESTION,
        "case_id": CASE,
        "intent": "observational_summary",
        "target_quantity": "burned_area_ha",
        "period_start": "2015-09-01T00:00:00Z",
        "period_end": "2015-10-01T00:00:00Z",
    }
    return {**base, **overrides}


def typed_message(data: dict[str, Any], media_type: str = REQUEST_MEDIA_TYPE) -> Message:
    return Message(
        message_id="m-1",
        role=Role.ROLE_USER,
        parts=[new_data_part(data, media_type=media_type)],
    )


class FakeEngineer:
    """A port that records its jobs. With `hold`, each run waits until a test releases it."""

    def __init__(self, *, hold: bool = False, fault: Exception | None = None):
        self.jobs: list[EngineerJob] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.saw_cancel = threading.Event()
        self._hold = hold
        self._fault = fault

    def run(self, job: EngineerJob, cancel: threading.Event) -> EngineerOutcome:
        self.jobs.append(job)
        self.started.set()
        if self._fault is not None:
            raise self._fault
        while self._hold and not self.release.is_set():
            if cancel.is_set():
                self.saw_cancel.set()
                break
            time.sleep(0.005)
        return outcome(job)


def outcome(job: EngineerJob) -> EngineerOutcome:
    author = RoleCall(
        role_id="geospatial_engineer", provider="fake", model="fake", logical_model="fake"
    )
    reply = EngineeringReplyV1(
        task_id=job.task.task_id,
        status="verified",
        plan_sha256=(DIGEST,),
        critic_verdicts=("approved",),
        supported_finding_ids=("A1.1",),
        limitation_reasons=(),
        elapsed_ms=1,
        author=author,
    )
    return EngineerOutcome(
        reply=reply, source_sha256=(DIGEST,), result_sha256=DIGEST, trace_head_sha256=DIGEST
    )


@dataclass(frozen=True)
class LiveAgent:
    url: str
    runs_root: Path

    async def _use(
        self,
        action: Callable[[Client], Awaitable[T]],
        token: str | None,
        polling: bool,
        timeout: float,
    ) -> T:
        headers = {} if token is None else {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(headers=headers, timeout=timeout) as http:
            config = ClientConfig(httpx_client=http, streaming=False, polling=polling)
            client = await create_client(self.url, config)
            return await action(client)

    def call(
        self,
        action: Callable[[Client], Awaitable[T]],
        token: str | None = TOKEN,
        *,
        polling: bool = False,
        timeout: float = 30.0,
    ) -> T:
        """One action through a fresh official client, on its own connection."""
        return asyncio.run(self._use(action, token, polling, timeout))

    def send(self, data: dict[str, Any], **kwargs: Any) -> Task:
        return self.send_message(typed_message(data), **kwargs)

    def send_message(self, message: Message, **kwargs: Any) -> Task:
        return self.call(lambda client: first_task(client, message), **kwargs)

    def get(self, task_id: str, **kwargs: Any) -> Task:
        return self.call(lambda c: c.get_task(GetTaskRequest(id=task_id)), **kwargs)

    def rpc(
        self, body: bytes, *, token: str = TOKEN, version: str | None = "1.0"
    ) -> httpx.Response:
        """Raw bytes to the endpoint, for faults the official client cannot produce."""
        headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
        if version is not None:
            headers[VERSION_HEADER] = version
        return httpx.post(f"{self.url}/a2a", content=body, headers=headers, timeout=10.0)


async def first_task(client: Client, message: Message) -> Task:
    async for event in client.send_message(SendMessageRequest(message=message)):
        return event.task
    raise AssertionError("the server sent no event")


def wait_for(check: Callable[[], bool], seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, "the condition did not become true in time"
        time.sleep(0.005)


@contextmanager
def live_agent(
    engineer: EngineerPort,
    cases: CaseLibrary,
    root: Path,
    *,
    limit: Budget | None = None,
    quota: Quota | None = None,
) -> Iterator[LiveAgent]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    settings = AgentSettings(url, root, limit or Budget(), quota or Quota(max_running=2))
    app = build_app(engineer, cases, PEERS, settings)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    wait_for(lambda: server.started)
    try:
        yield LiveAgent(url, root)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
