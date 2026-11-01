"""Ask one implementor worker for a patch, screen it, and record the trial. Nothing runs.

Every worker, Meta or not, gets the same task text, the same interface and the same
budget. The worker answers in text with one unified diff; it has no tools. A patch the
screen blocks gets one revision with the findings. The trial then waits for the trusted
runner and a human: acceptance() reports `execution` until a runner record exists.

A trial keeps every proposal and how each reply ended, so a token stop or a provider fault
is not read as a worker that declined. It records the length of any reasoning, never its
text.

This module never imports, applies or executes the proposed code.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.implement.bindings import BindingRefused, RoleBinding
from earthlab.implement.catalogue import TaskSpec
from earthlab.implement.contracts import (
    Acceptance,
    CallUsage,
    ImplementationResultV1,
    ReviewFindingV1,
    WorkerIdentity,
    acceptance,
    sha256_text,
)
from earthlab.implement.screen import screen_patch
from earthlab.llm.client import ChatClient
from earthlab.llm.types import ChatResponse, ProviderError, ProviderErrorKind

_DIFF = re.compile(r"```(?:diff|patch)?\n(.*?)```", re.DOTALL)
WORKER_SYSTEM = """\
You are an implementation worker. Write the module the task asks for and reply with one
unified git diff in a ```diff block, creating only the allowed path. Use only the Python
standard library or numpy. Do not read or write files, start processes, use the network,
or change tests. Your patch will be screened, run by a separate trusted runner against
frozen tests, and reviewed by a human. You cannot run anything yourself.
"""


Status = Literal["screened", "blocked", "declined", "truncated", "provider_error"]


class ImplementorTrialV1(Strict):
    """One worker's attempt at one task, as the harness saw it."""

    schema_version: Literal["1"] = "1"
    task_id: str
    worker: WorkerIdentity
    status: Status
    result: ImplementationResultV1 | None
    proposals: tuple[ImplementationResultV1, ...] = ()  # every attempt, oldest first
    finish_reason: str | None = None  # of the last reply
    reasoning_chars: int = Field(default=0, ge=0)  # over all replies
    findings: tuple[ReviewFindingV1, ...] = ()
    acceptance: Acceptance | None = None
    model_calls: int = Field(ge=0)
    revisions: int = Field(ge=0, le=1)
    error: str | None = None


def task_prompt(spec: TaskSpec) -> str:
    t = spec.task
    body = {
        "task_id": t.task_id,
        "method": t.method_ref,
        "allowed_paths": list(t.allowed_paths),
        "requirements": list(t.requirements),
        "interface": spec.interface,
        "fixed_tests": list(t.fixed_tests),
    }
    return json.dumps(body, indent=1)


def extract_diff(text: str) -> str:
    match = _DIFF.search(text)
    return (match.group(1) if match else "").strip("\n") + ("\n" if match else "")


def _identity(binding: RoleBinding, client: ChatClient, served: str | None) -> WorkerIdentity:
    if binding.role != "implementor":
        raise BindingRefused(f"{binding.candidate_id} is bound to {binding.role}, not implementor")
    cfg = client.config
    if (cfg.name, cfg.model) != (binding.provider_id, binding.model_id):
        raise BindingRefused(f"implementor is bound to {binding.provider_id}/{binding.model_id}")
    return WorkerIdentity(
        worker_id=binding.candidate_id,
        model_family=binding.family,
        model_id=binding.model_id,
        provider_id=binding.provider_id,
        served_model=served,
    )


def _proposal(
    spec: TaskSpec, identity: WorkerIdentity, text: str, calls: int, tokens: list[int], t0: float
) -> ImplementationResultV1:
    diff = extract_diff(text)
    usage = CallUsage(
        model_calls=calls, prompt_tokens=tokens[0], completion_tokens=tokens[1],
        wall_seconds=round(time.perf_counter() - t0, 3),
    )  # fmt: skip
    return ImplementationResultV1(
        task_id=spec.task.task_id, worker=identity,
        status="proposed" if diff.strip() else "declined", patch_diff=diff,
        artifact_sha256=sha256_text(diff), usage=usage,
    )  # fmt: skip


def _blocked_note(findings: tuple[ReviewFindingV1, ...]) -> str:
    lines = "\n".join(f"- {f.check_id}: {f.message}" for f in findings)
    return f"The screen blocked the patch:\n{lines}"


def _empty_reply(resp: ChatResponse) -> bool:
    """A reply with no text and no generated tokens is a provider fault, not a decision."""
    generated = resp.usage.completion_tokens
    return generated == 0 or (generated is None and not resp.content.strip())


@dataclass
class _Attempts:
    """What one trial has seen so far."""

    spec: TaskSpec
    worker: WorkerIdentity
    started: float = field(default_factory=time.perf_counter)
    calls: int = 0
    tokens: list[int] = field(default_factory=lambda: [0, 0])
    reasoning_chars: int = 0
    finish_reason: str | None = None
    proposals: list[ImplementationResultV1] = field(default_factory=list)
    findings: tuple[ReviewFindingV1, ...] = ()

    def saw(self, resp: ChatResponse) -> None:
        self.finish_reason = resp.finish_reason
        self.reasoning_chars += len(resp.reasoning or "")

    def counted(self, resp: ChatResponse) -> None:
        self.tokens[0] += resp.usage.prompt_tokens or 0
        self.tokens[1] += resp.usage.completion_tokens or 0

    def trial(self, status: Status, error: str | None = None) -> ImplementorTrialV1:
        last = self.proposals[-1] if self.proposals else None
        return ImplementorTrialV1(
            task_id=self.spec.task.task_id, worker=self.worker, status=status, result=last,
            proposals=tuple(self.proposals), findings=self.findings,
            finish_reason=self.finish_reason, reasoning_chars=self.reasoning_chars,
            acceptance=None if error or last is None
            else acceptance(self.spec.task, last, self.findings),
            model_calls=self.calls, revisions=max(0, self.calls - 1), error=error,
        )  # fmt: skip


def run_trial(
    spec: TaskSpec, client: ChatClient, binding: RoleBinding, *, max_tokens: int = 4096
) -> ImplementorTrialV1:
    """One proposal and at most one revision, within the task's model-call budget."""
    log = _Attempts(spec, _identity(binding, client, None))
    messages = [
        {"role": "system", "content": WORKER_SYSTEM},
        {"role": "user", "content": task_prompt(spec)},
    ]
    for _ in range(min(2, spec.task.budget.max_model_calls)):
        log.calls += 1
        try:
            resp = client.chat(
                messages, [], max_tokens=max_tokens, temperature=0.2, tool_choice="none"
            )
        except ProviderError as exc:
            return log.trial("provider_error", exc.kind.value)
        log.saw(resp)
        if _empty_reply(resp):
            return log.trial("provider_error", ProviderErrorKind.MALFORMED.value)
        log.counted(resp)
        log.worker = _identity(binding, client, resp.served_model)
        result = _proposal(spec, log.worker, resp.content, log.calls, log.tokens, log.started)
        if result.status == "declined":
            # A revision with no patch leaves the blocked proposal and its findings standing.
            if log.proposals:
                return log.trial("blocked")
            log.proposals.append(result)
            return log.trial("truncated" if resp.finish_reason == "length" else "declined")
        log.proposals.append(result)
        log.findings = screen_patch(spec.task, result)
        if not log.findings:
            return log.trial("screened")
        messages += [
            {"role": "assistant", "content": resp.content},
            {"role": "user", "content": _blocked_note(log.findings)},
        ]
    return log.trial("blocked")
