"""Hard limits for one investigation. Enforced in code; the model cannot raise them.

Every model call and every tool call is checked before it runs, including each call in a
batch. A model call reserves its worst-case cost first: the prompt is at most one token per
byte, and the reply is at most max_output_tokens. A hosted provider without a price in the
config is refused, never counted as free. After the call, the reported usage replaces the
reservation; if usage is missing, the worst case stays charged.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.llm.providers import ProviderConfig
from earthlab.llm.types import Usage


class Budget(Strict):
    max_turns: int = Field(default=12, gt=0, le=50)
    max_tool_calls: int = Field(default=24, gt=0, le=100)
    max_submissions: int = Field(default=3, gt=0, le=10)
    max_seconds: float = Field(default=3600.0, gt=0)
    max_usd: float = Field(default=1.0, ge=0)
    max_output_tokens: int = Field(default=4096, gt=0, le=32768)


class BudgetStop(Exception):
    """A limit would be crossed by the next action; the action did not run."""


def prompt_bytes(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> int:
    """Upper bound on prompt tokens: every token is at least one byte of the request."""
    return len(json.dumps([messages, tools], ensure_ascii=False).encode("utf-8"))


class BudgetMeter:
    def __init__(self, budget: Budget, clock: Callable[[], float] = time.monotonic):
        self.budget = budget
        self.turns = 0
        self.tool_calls = 0
        self.submissions = 0
        self.cost_usd = 0.0
        self._clock = clock
        self._started = clock()

    def elapsed(self) -> float:
        return self._clock() - self._started

    def remaining_seconds(self) -> float:
        return max(0.0, self.budget.max_seconds - self.elapsed())

    def exhausted(self) -> str | None:
        """The first limit reached, or None while work may continue."""
        b = self.budget
        if self.turns >= b.max_turns:
            return f"turn limit {b.max_turns} reached"
        if self.tool_calls >= b.max_tool_calls:
            return f"tool-call limit {b.max_tool_calls} reached"
        if self.elapsed() >= b.max_seconds:
            return f"time limit {b.max_seconds:.0f}s reached"
        if self.cost_usd > b.max_usd:
            return f"estimated cost above {b.max_usd} USD"
        return None

    def worst_case_usd(self, config: ProviderConfig, request_bytes: int) -> float | None:
        """None when a billed provider has no price: the call must not run."""
        price_in, price_out = config.usd_per_mtok_input, config.usd_per_mtok_output
        if price_in is None or price_out is None:
            return None if config.kind == "hosted" else 0.0
        return (request_bytes * price_in + self.budget.max_output_tokens * price_out) / 1e6

    def reserve_model_call(self, config: ProviderConfig, request_bytes: int) -> float:
        """Check every limit for one model call and return its worst-case cost."""
        if self.turns >= self.budget.max_turns:
            raise BudgetStop(f"turn limit {self.budget.max_turns} reached")
        if self.remaining_seconds() <= 0:
            raise BudgetStop(f"time limit {self.budget.max_seconds:.0f}s reached")
        worst = self.worst_case_usd(config, request_bytes)
        if worst is None:
            raise BudgetStop(f"{config.name} is hosted and has no price in the config; refused")
        if self.cost_usd + worst > self.budget.max_usd:
            raise BudgetStop(
                f"next model call could cost {worst:.4f} USD; "
                f"{self.cost_usd:.4f} of {self.budget.max_usd} USD already spent"
            )
        self.turns += 1
        return worst

    def settle_model_call(self, config: ProviderConfig, usage: Usage, worst: float) -> float:
        """Charge the reported cost, or the reserved worst case when usage is missing."""
        cost = config.estimate_cost_usd(usage.prompt_tokens, usage.completion_tokens)
        charged = worst if cost is None else cost
        self.cost_usd += charged
        return charged

    def check_tool_call(self, is_submission: bool) -> str | None:
        """Why the next tool call in a batch must be skipped, or None if it may run."""
        b = self.budget
        if self.tool_calls >= b.max_tool_calls:
            return f"tool-call limit {b.max_tool_calls} reached"
        if self.remaining_seconds() <= 0:
            return f"time limit {b.max_seconds:.0f}s reached"
        if is_submission and self.submissions >= b.max_submissions:
            return f"submission limit {b.max_submissions} reached"
        return None
