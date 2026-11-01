"""The narrow interface to the engineer, and its implementation on the existing path.

`InvestigatorEngineer` runs the same `investigate` call as the workflow's engineer stage:
plan review on, one case, the scope from `task_scope`, the guard, and the job's budget. The
A2A layer sees only `EngineerPort`, so it cannot reach a tool or a provider.

Cancellation is cooperative. `investigate` has no stop signal, so `_StoppableClient` ends
the run before its next model call. A model call already in flight, and the tool calls of a
reply already received, finish first. The run then stops as `provider_error`, with a trace
reason that names the cancel.
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from earthlab.a2a.admission import EngineerJob
from earthlab.agent.budget import Budget
from earthlab.agent.loop import Investigation
from earthlab.contracts import Strict
from earthlab.digest import file_digest, payload_digest
from earthlab.implement.bindings import BindingRefused
from earthlab.llm.client import ChatClient
from earthlab.llm.providers import ProviderConfig
from earthlab.llm.types import ChatResponse, ProviderError, ProviderErrorKind
from earthlab.metrics import EarthlabMetrics
from earthlab.runtime import DEFAULT_OPTIONS, RunOptions, Workspace, investigate
from earthlab.safety.llama_guard import LlamaGuard
from earthlab.trace import RunTrace
from earthlab.workflow.assign import WorkflowAssignment, task_scope
from earthlab.workflow.contracts import EngineeringReplyV1, EngineeringTaskV1, RoleCall
from earthlab.workflow.prompts import engineer_prompt

# Shared on purpose: the scope limit and the finding filter must stay one implementation.
from earthlab.workflow.run import _only, _reply

CANCEL_REASON = "cancelled by the A2A peer"


class EngineerOutcome(Strict):
    """What the port gives back: the typed reply and the digests of the saved run."""

    reply: EngineeringReplyV1
    source_sha256: tuple[str, ...]
    result_sha256: str
    trace_head_sha256: str


class EngineerPort(Protocol):
    """Run one admitted job to its end. `cancel` asks the run to stop early."""

    def run(self, job: EngineerJob, cancel: threading.Event) -> EngineerOutcome: ...


class _StoppableClient:
    """The bound client, with a cancel check before each model call."""

    def __init__(self, client: ChatClient, cancel: threading.Event):
        self.config: ProviderConfig = client.config
        self._client = client
        self._cancel = cancel

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
        tool_choice: str = "auto",
        timeout: float | None = None,
    ) -> ChatResponse:
        if self._cancel.is_set():
            raise ProviderError(ProviderErrorKind.BAD_REQUEST, CANCEL_REASON)
        return self._client.chat(
            messages,
            tools,
            max_tokens=max_tokens,
            temperature=temperature,
            tool_choice=tool_choice,
            timeout=timeout,
        )


def _author(cfg: ProviderConfig, result: Investigation) -> RoleCall:
    return RoleCall(
        role_id="geospatial_engineer",
        provider=cfg.name,
        model=cfg.model,
        logical_model=cfg.logical_model,
        served_model=result.served_model,
    )


def _head(path: Path) -> str:
    """The digest of the last entry, after a check of the whole chain."""
    trace = RunTrace(path)
    trace.verify()
    return str(list(trace.records())[-1]["hash"])


class InvestigatorEngineer:
    """The bound engineer client on the pinned workspace. It adds no tool and no permission."""

    def __init__(
        self,
        client: ChatClient,
        workspace: Workspace,
        assignment: WorkflowAssignment,
        *,
        metrics: EarthlabMetrics | None = None,
        guard: LlamaGuard | None = None,
        reasoning: str = "medium",
        options: RunOptions = DEFAULT_OPTIONS,
    ):
        bound, cfg = assignment.engineer, client.config
        if (cfg.name, cfg.model) != (bound.provider_id, bound.model_id):
            raise BindingRefused(
                f"{bound.role} is bound to {bound.provider_id}/{bound.model_id}, "
                f"but the client is {cfg.name}/{cfg.model}"
            )
        self._client = client
        self._workspace = workspace
        self._metrics = metrics or EarthlabMetrics()
        self._guard = guard
        self._reasoning = reasoning
        self._options = options

    def run(self, job: EngineerJob, cancel: threading.Event) -> EngineerOutcome:
        task = job.task
        self._hand_off(job)
        started = time.perf_counter()
        result = self._investigate(job, _StoppableClient(self._client, cancel), job.budget)
        elapsed = round((time.perf_counter() - started) * 1000)
        return EngineerOutcome(
            reply=_reply(task, result, elapsed, _author(self._client.config, result)),
            source_sha256=(self._workspace.snapshot.sha256,),
            result_sha256=file_digest(job.run_dir / "result.json"),
            trace_head_sha256=_head(job.run_dir / "trace.jsonl"),
        )

    def _hand_off(self, job: EngineerJob) -> None:
        """Start the run's hash chain with the A2A IDs, so a peer's trace ID finds this run."""
        dumped = job.task.model_dump(mode="json")
        RunTrace(job.run_dir / "trace.jsonl").append(
            "task_handoff", "runtime", task_id=job.task.task_id,
            parent_task_id=job.task.parent_task_id, receiver="geospatial_engineer",
            brief_sha256=job.task.brief_sha256, task_sha256=payload_digest(dumped), task=dumped,
            a2a={
                "task_id": job.a2a_task_id, "context_id": job.context_id, "peer": job.peer,
                "trace_id": job.request.trace_id,
            },
        )  # fmt: skip

    def _investigate(self, job: EngineerJob, client: ChatClient, budget: Budget) -> Investigation:
        cases = self._workspace.cases
        if cases is None:
            raise ValueError("the engineer needs registered cases")
        task: EngineeringTaskV1 = job.task
        scope = task_scope(cases.get(task.case_id))
        return investigate(
            engineer_prompt(task, job.brief, job.request.question),
            client,
            replace(self._workspace, cases=_only(cases, task.case_id)),
            job.run_dir,
            metrics=self._metrics,
            budget=budget,
            reasoning=self._reasoning,
            guard=self._guard,
            options=replace(self._options, plan_review=True, scope=scope),
        )
