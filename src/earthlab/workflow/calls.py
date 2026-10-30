"""Model calls for a workflow role, metered and traced like the investigator's."""

from __future__ import annotations

from typing import Any

from earthlab.agent.budget import BudgetMeter, prompt_bytes
from earthlab.agent.loop import PLANNER_TEMPERATURE
from earthlab.llm.client import ChatClient
from earthlab.llm.types import ChatResponse, ProviderError, Usage
from earthlab.metrics import EarthlabMetrics
from earthlab.trace import RunTrace
from earthlab.workflow.contracts import RoleCall


class RoleCalls:
    """Every model call one role makes in a run; counts and served model are kept."""

    def __init__(self, role: str, client: ChatClient, trace: RunTrace, metrics: EarthlabMetrics):
        self.role = role
        self.client = client
        self.trace = trace
        self.metrics = metrics
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.served_model: str | None = None

    def call(
        self,
        meter: BudgetMeter,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str,
    ) -> ChatResponse:
        """Reserve the worst case, call once, charge and trace. Raises on any limit or error."""
        cfg = self.client.config
        worst = meter.reserve_model_call(cfg, prompt_bytes(messages, tools))
        self.calls += 1
        try:
            resp = self.client.chat(
                messages,
                tools,
                max_tokens=meter.budget.max_output_tokens,
                temperature=PLANNER_TEMPERATURE,
                tool_choice=tool_choice,
                timeout=min(cfg.timeout_seconds, meter.remaining_seconds()),
            )
        except ProviderError as exc:
            meter.settle_model_call(cfg, Usage(), worst)  # a failed call may still be billed
            self.metrics.record_inference(cfg.name, cfg.logical_model, exc.kind.value, None)
            self.trace.append(
                "model_error", "runtime", kind=exc.kind.value, attempt=1, max_attempts=1,
                retrying=False, role=self.role,
            )  # fmt: skip
            raise
        meter.settle_model_call(cfg, resp.usage, worst)
        self._record(resp)
        return resp

    def _record(self, resp: ChatResponse) -> None:
        cfg, usage = self.client.config, resp.usage
        self.prompt_tokens += usage.prompt_tokens or 0
        self.completion_tokens += usage.completion_tokens or 0
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
