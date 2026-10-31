"""Ask one implementor worker for a patch, screen it, and record the trial. Nothing runs.

Every worker, Meta or not, gets the same task text, the same interface and the same
budget. The worker answers in text with one unified diff; it has no tools. A patch the
screen blocks gets one revision with the findings. The trial then waits for the trusted
runner and a human: acceptance() reports `execution` until a runner record exists.

This module never imports, applies or executes the proposed code.
"""

from __future__ import annotations

import json
import re
import time
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
from earthlab.llm.types import ProviderError

_DIFF = re.compile(r"```(?:diff|patch)?\n(.*?)```", re.DOTALL)
WORKER_SYSTEM = """\
You are an implementation worker. Write the module the task asks for and reply with one
unified git diff in a ```diff block, creating only the allowed path. Use only the Python
standard library or numpy. Do not read or write files, start processes, use the network,
or change tests. Your patch will be screened, run by a separate trusted runner against
frozen tests, and reviewed by a human. You cannot run anything yourself.
"""


class ImplementorTrialV1(Strict):
    """One worker's attempt at one task, as the harness saw it."""

    schema_version: Literal["1"] = "1"
    task_id: str
    worker: WorkerIdentity
    status: Literal["screened", "blocked", "declined", "provider_error"]
    result: ImplementationResultV1 | None
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


def run_trial(
    spec: TaskSpec, client: ChatClient, binding: RoleBinding, *, max_tokens: int = 4096
) -> ImplementorTrialV1:
    """One proposal and at most one revision, within the task's model-call budget."""
    identity = _identity(binding, client, None)
    messages = [
        {"role": "system", "content": WORKER_SYSTEM},
        {"role": "user", "content": task_prompt(spec)},
    ]
    calls, started, tokens = 0, time.perf_counter(), [0, 0]
    result: ImplementationResultV1 | None = None
    findings: tuple[ReviewFindingV1, ...] = ()
    for revision in range(min(2, spec.task.budget.max_model_calls)):
        try:
            resp = client.chat(
                messages, [], max_tokens=max_tokens, temperature=0.2, tool_choice="none"
            )
        except ProviderError as exc:
            return ImplementorTrialV1(
                task_id=spec.task.task_id, worker=identity, status="provider_error",
                result=result, findings=findings, model_calls=calls + 1,
                revisions=revision, error=exc.kind.value,
            )  # fmt: skip
        calls += 1
        tokens[0] += resp.usage.prompt_tokens or 0
        tokens[1] += resp.usage.completion_tokens or 0
        identity = _identity(binding, client, resp.served_model)
        result = _proposal(spec, identity, resp.content, calls, tokens, started)
        findings = screen_patch(spec.task, result)
        if result.status == "declined" or not findings:
            break
        messages += [
            {"role": "assistant", "content": resp.content},
            {"role": "user", "content": _blocked_note(findings)},
        ]
    status: Literal["screened", "blocked", "declined"] = (
        "declined" if result is None or result.status == "declined"
        else "blocked" if findings else "screened"
    )  # fmt: skip
    return ImplementorTrialV1(
        task_id=spec.task.task_id, worker=identity, status=status, result=result,
        findings=findings, model_calls=calls, revisions=max(0, calls - 1),
        acceptance=None if result is None else acceptance(spec.task, result, findings),
    )  # fmt: skip
