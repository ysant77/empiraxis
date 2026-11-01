"""The SDK's AgentExecutor: admission, the engineer worker and the task's state changes.

The engineer runs in a worker thread. A cancel marks the A2A task canceled at once and
signals the worker, but the worker's running slot stays taken until it really stops. The
adapter's own hash chain, `a2a_trace.jsonl`, records each step beside the run's trace.
"""

from __future__ import annotations

import asyncio
import functools
import threading
from pathlib import Path

from a2a.helpers.proto_helpers import new_data_part, new_task, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types.a2a_pb2 import Message, Part, TaskState

from earthlab.a2a.admission import EngineerJob, admit, request_digest
from earthlab.a2a.contracts import (
    REFUSAL_MEDIA_TYPE,
    REPORT_MEDIA_TYPE,
    EngineerRunReportV1,
    EngineerTaskRequestV1,
    RefusalV1,
)
from earthlab.a2a.engineer import EngineerOutcome, EngineerPort
from earthlab.a2a.ledger import RequestLedger, Ticket
from earthlab.agent.budget import Budget
from earthlab.cases.tools import CaseLibrary
from earthlab.digest import payload_digest
from earthlab.trace import RunTrace
from earthlab.workflow.contracts import WorkflowStatus

REQUEST_KEY = "earthlab_request"
TICKET_KEY = "earthlab_ticket"

_FAILED: frozenset[WorkflowStatus] = frozenset({"budget_exhausted", "provider_error", "failed"})
_REJECTED: frozenset[WorkflowStatus] = frozenset({"refused", "needs_input", "out_of_scope"})


def task_state(status: WorkflowStatus) -> TaskState:
    """The A2A state for a run status. An abstention is a completed, honest answer."""
    if status in _FAILED:
        return TaskState.TASK_STATE_FAILED
    if status in _REJECTED:
        return TaskState.TASK_STATE_REJECTED
    return TaskState.TASK_STATE_COMPLETED


def run_report(job: EngineerJob, outcome: EngineerOutcome) -> EngineerRunReportV1:
    reply = outcome.reply
    return EngineerRunReportV1(
        a2a_task_id=job.a2a_task_id,
        context_id=job.context_id,
        request_id=job.request.request_id,
        trace_id=job.request.trace_id,
        request_sha256=request_digest(job.request),
        engineering_task_id=job.task.task_id,
        engineering_task_sha256=payload_digest(job.task.model_dump(mode="json")),
        status=reply.status,
        verified_finding_ids=reply.supported_finding_ids,
        limitation_reasons=reply.limitation_reasons,
        plan_sha256=reply.plan_sha256,
        critic_verdicts=reply.critic_verdicts,
        source_sha256=outcome.source_sha256,
        result_sha256=outcome.result_sha256,
        trace_head_sha256=outcome.trace_head_sha256,
        provider=reply.author.provider,
        model=reply.author.model,
        served_model=reply.author.served_model,
        elapsed_ms=reply.elapsed_ms,
    )


class EngineerExecutor(AgentExecutor):
    """One instance serves the whole server. `execute` runs once per claimed request."""

    def __init__(
        self,
        engineer: EngineerPort,
        cases: CaseLibrary,
        limit: Budget,
        ledger: RequestLedger,
        runs_root: Path,
    ):
        self._engineer = engineer
        self._cases = cases
        self._limit = limit
        self._ledger = ledger
        self._runs_root = runs_root
        self._stops: dict[str, threading.Event] = {}
        self._workers: set[asyncio.Future[EngineerOutcome | None]] = set()  # strong references

    def _trace(self, task_id: str) -> RunTrace:
        return RunTrace(self._runs_root / task_id / "a2a_trace.jsonl")

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        state = context.call_context.state
        ticket: Ticket = state[TICKET_KEY]
        request: EngineerTaskRequestV1 = state[REQUEST_KEY]
        updater = TaskUpdater(event_queue, ticket.task_id, ticket.context_id)
        worker_owns_slot = False
        try:
            history = [] if context.message is None else [context.message]
            await event_queue.enqueue_event(
                new_task(
                    ticket.task_id,
                    ticket.context_id,
                    TaskState.TASK_STATE_SUBMITTED,
                    history=history,
                )
            )
            self._trace(ticket.task_id).append(
                "a2a_received", "a2a", a2a_task_id=ticket.task_id, context_id=ticket.context_id,
                peer=ticket.owner, request_id=request.request_id, trace_id=request.trace_id,
                request_sha256=ticket.digest,
            )  # fmt: skip
            admitted = admit(
                request, a2a_task_id=ticket.task_id, context_id=ticket.context_id,
                peer=ticket.owner, cases=self._cases, limit=self._limit,
                run_dir=self._runs_root / ticket.task_id,
            )  # fmt: skip
            if isinstance(admitted, RefusalV1):
                await self._refuse(updater, ticket, admitted)
                return
            await updater.start_work()
            worker = self._start(admitted)
            worker_owns_slot = True
            await self._finish(updater, admitted, await asyncio.shield(worker))
        finally:
            if not worker_owns_slot:
                self._ledger.release(ticket.owner)

    async def _refuse(self, updater: TaskUpdater, ticket: Ticket, refusal: RefusalV1) -> None:
        dumped = refusal.model_dump(mode="json")
        self._trace(ticket.task_id).append("a2a_refused", "a2a", **dumped)
        part = new_data_part(dumped, media_type=REFUSAL_MEDIA_TYPE)
        await updater.reject(updater.new_agent_message([part]))

    def _start(self, job: EngineerJob) -> asyncio.Future[EngineerOutcome | None]:
        stop = self._stops[job.a2a_task_id] = threading.Event()
        worker = asyncio.ensure_future(self._work(job, stop))
        self._workers.add(worker)
        worker.add_done_callback(functools.partial(self._stopped, job))
        return worker

    async def _work(self, job: EngineerJob, stop: threading.Event) -> EngineerOutcome | None:
        """The outcome, or None after an engineer fault. The peer never sees fault text."""
        try:
            return await asyncio.to_thread(self._engineer.run, job, stop)
        except Exception as exc:
            self._trace(job.a2a_task_id).append("a2a_fault", "a2a", kind=type(exc).__name__)
            return None

    def _stopped(self, job: EngineerJob, worker: asyncio.Future[EngineerOutcome | None]) -> None:
        """The worker has really ended: free its slot and record that it stopped."""
        self._workers.discard(worker)
        self._stops.pop(job.a2a_task_id, None)
        self._ledger.release(job.peer)
        self._trace(job.a2a_task_id).append("a2a_worker_stopped", "a2a")

    async def _finish(
        self, updater: TaskUpdater, job: EngineerJob, outcome: EngineerOutcome | None
    ) -> None:
        if outcome is None:
            await updater.failed(_text(updater, "the engineer stopped with an internal fault"))
            return
        report = run_report(job, outcome)
        dumped = report.model_dump(mode="json")
        self._trace(job.a2a_task_id).append(
            "a2a_report", "a2a", status=report.status, report_sha256=payload_digest(dumped),
        )  # fmt: skip
        part: Part = new_data_part(dumped, media_type=REPORT_MEDIA_TYPE)
        await updater.add_artifact([part], name="engineer-run-report", last_chunk=True)
        await updater.update_status(task_state(report.status))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id, context_id = context.task_id, context.context_id
        if task_id is None or context_id is None:
            raise ValueError("cancel needs a task and a context")
        stop = self._stops.get(task_id)
        if stop is not None:
            stop.set()
        self._trace(task_id).append("a2a_cancel_requested", "a2a", worker_running=stop is not None)
        await TaskUpdater(event_queue, task_id, context_id).cancel()


def _text(updater: TaskUpdater, text: str) -> Message:
    return updater.new_agent_message([new_text_part(text)])
