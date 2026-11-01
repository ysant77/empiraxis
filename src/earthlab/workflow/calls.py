"""Model calls for a workflow role, metered and traced like the investigator's.

Every attempt, failed or not, is charged to the run's shared ledger. A transient failure
may get one more attempt under the run's retry policy (earthlab.llm.retry), only if the
stage meter still has room; the same failure kinds retry as for the investigator.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from earthlab.agent.budget import BudgetMeter, BudgetStop, prompt_bytes
from earthlab.agent.loop import PLANNER_TEMPERATURE
from earthlab.llm.client import ChatClient
from earthlab.llm.retry import NO_RETRY, RetryPolicy
from earthlab.llm.types import ChatResponse, ProviderError, Usage
from earthlab.metrics import EarthlabMetrics
from earthlab.trace import RunTrace
from earthlab.workflow.contracts import RoleCall
from earthlab.workflow.ledger import WorkflowLedger

Messages = list[dict[str, Any]]


def client_kind(client: ChatClient) -> str:
    """live_http only for the real HTTP clients; anything else (scripted test clients
    included) is scripted_or_other, so a test run can never be shown as live."""
    from earthlab.llm.client import OpenAICompatClient
    from earthlab.llm.raw import RawCompletionClient

    live = isinstance(client, OpenAICompatClient | RawCompletionClient)
    return "live_http" if live else "scripted_or_other"


class RoleCalls:
    """Every model call one role makes in a run; counts and served model are kept."""

    def __init__(
        self,
        role: str,
        client: ChatClient,
        trace: RunTrace,
        metrics: EarthlabMetrics,
        ledger: WorkflowLedger,
        retry: RetryPolicy = NO_RETRY,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.role = role
        self.client = client
        self.trace = trace
        self.metrics = metrics
        self.ledger = ledger
        self.retry = retry
        self.sleep = sleep
        self.calls = 0
        self.served_model: str | None = None

    def call(
        self, meter: BudgetMeter, messages: Messages, tools: Messages, tool_choice: str
    ) -> ChatResponse:
        """One model call under the retry policy. Raises BudgetStop or ProviderError."""
        return self.retry.run(
            lambda attempt: self._attempt(meter, messages, tools, tool_choice, attempt),
            lambda exc: self._blocker(meter, messages, tools, exc),
            self.sleep,
        )

    def _blocker(
        self, meter: BudgetMeter, messages: Messages, tools: Messages, exc: ProviderError
    ) -> str | None:
        reason = None
        if self.retry.delay(exc) >= meter.remaining_seconds():
            reason = "retry delay would outlast the time left"
        else:
            try:
                meter.check_model_call(self.client.config, prompt_bytes(messages, tools))
            except BudgetStop as stop:
                reason = str(stop)
        if reason is not None:
            self.trace.append("model_retry_skipped", "runtime", kind=exc.kind.value, reason=reason)
        return reason

    def _attempt(
        self, meter: BudgetMeter, messages: Messages, tools: Messages, choice: str, attempt: int
    ) -> ChatResponse:
        cfg = self.client.config
        worst = meter.reserve_model_call(cfg, prompt_bytes(messages, tools))
        self.calls += 1
        started = time.perf_counter()
        try:
            resp = self.client.chat(
                messages,
                tools,
                max_tokens=meter.budget.max_output_tokens,
                temperature=PLANNER_TEMPERATURE,
                tool_choice=choice,
                timeout=min(cfg.timeout_seconds, meter.remaining_seconds()),
            )
        except ProviderError as exc:
            charged = meter.settle_model_call(cfg, Usage(), worst)  # may still be billed
            self.ledger.charge(self.role, model_calls=1, cost_usd=charged)
            self.metrics.record_inference(cfg.name, cfg.logical_model, exc.kind.value, None)
            self.trace.append(
                "model_error", "runtime", kind=exc.kind.value, attempt=attempt,
                max_attempts=self.retry.max_attempts, retrying=self.retry.retries(exc, attempt),
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                charged_usd=round(charged, 6), role=self.role,
            )  # fmt: skip
            raise
        charged = meter.settle_model_call(cfg, resp.usage, worst)
        self._record(resp, charged)
        return resp

    def _record(self, resp: ChatResponse, charged: float) -> None:
        cfg, usage = self.client.config, resp.usage
        self.ledger.charge(
            self.role,
            model_calls=1,
            prompt_tokens=usage.prompt_tokens,  # None when the provider did not report it
            completion_tokens=usage.completion_tokens,
            cost_usd=charged,
        )
        self.served_model = resp.served_model or self.served_model
        tokens = (usage.prompt_tokens, usage.completion_tokens)
        cost = cfg.estimate_cost_usd(*tokens)
        self.metrics.record_inference(
            cfg.name, cfg.logical_model, "ok", resp.wall_seconds, tokens, cost
        )
        self.trace.append(
            "model_turn",
            "model",
            role=self.role,
            turn=self.calls,
            request_id=resp.request_id,
            served_model=resp.served_model,
            content=resp.content,
            reasoning=resp.reasoning,
            tool_calls=[c.model_dump() for c in resp.tool_calls],
            usage=usage.model_dump(),
            wall_seconds=round(resp.wall_seconds, 3),
        )

    def identity_record(self) -> dict[str, Any]:
        """Who served this role, for an experiment record: role, provider, model, calls."""
        cfg = self.client.config
        return {
            "role": self.role, "provider": cfg.name, "model": cfg.model,
            "served_model": self.served_model, "calls": self.calls,
            "kind": client_kind(self.client),
        }  # fmt: skip

    def identity(self) -> RoleCall:
        cfg = self.client.config
        return RoleCall.model_validate(
            {
                "role_id": self.role,
                "provider": cfg.name,
                "model": cfg.model,
                "logical_model": cfg.logical_model,
                "served_model": self.served_model,
            }
        )
