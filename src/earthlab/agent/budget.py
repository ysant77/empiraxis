"""Hard limits for one investigation. Enforced in code; the model cannot raise them."""

from __future__ import annotations

import time

from pydantic import Field

from earthlab.contracts import Strict


class Budget(Strict):
    max_turns: int = Field(default=12, gt=0, le=50)
    max_tool_calls: int = Field(default=24, gt=0, le=100)
    max_submissions: int = Field(default=3, gt=0, le=10)
    max_seconds: float = Field(default=3600.0, gt=0)
    max_usd: float = Field(default=1.0, ge=0)
    max_output_tokens: int = Field(default=4096, gt=0, le=32768)


class BudgetMeter:
    def __init__(self, budget: Budget):
        self.budget = budget
        self.turns = 0
        self.tool_calls = 0
        self.submissions = 0
        self.cost_usd = 0.0
        self._started = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self._started

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
