"""One budget for a whole workflow run, shared by every role.

Each stage (PM brief, engineer run, PM report) gets a stage budget cut from what is left,
and its measured use is charged back. A stage starts only when every limit still has room;
a stage cap (for example two PM calls) can lower a limit but never raise it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from earthlab.agent.budget import Budget


@dataclass
class RoleUsage:
    model_calls: int = 0
    tool_calls: int = 0
    prompt_tokens: int | None = 0  # None once any call did not report its usage
    completion_tokens: int | None = 0
    cost_usd: float = 0.0
    seconds: float = 0.0


@dataclass
class WorkflowLedger:
    budget: Budget
    clock: Callable[[], float] = time.monotonic
    usage: dict[str, RoleUsage] = field(default_factory=dict)
    started: float = 0.0

    def __post_init__(self) -> None:
        self.started = self.clock()

    def elapsed(self) -> float:
        return self.clock() - self.started

    def total(self) -> RoleUsage:
        out = RoleUsage(seconds=round(self.elapsed(), 3))
        for u in self.usage.values():
            out.model_calls += u.model_calls
            out.tool_calls += u.tool_calls
            out.prompt_tokens = _add(out.prompt_tokens, u.prompt_tokens)
            out.completion_tokens = _add(out.completion_tokens, u.completion_tokens)
            out.cost_usd += u.cost_usd
        return out

    def stage(self, max_turns: int | None = None) -> Budget | None:
        """The budget left for the next stage, or None when any limit has no room."""
        b, used = self.budget, self.total()
        turns = b.max_turns - used.model_calls
        tools = b.max_tool_calls - used.tool_calls
        seconds = b.max_seconds - self.elapsed()
        usd = b.max_usd - used.cost_usd
        if turns < 1 or tools < 1 or seconds <= 0 or usd < 0:
            return None
        return b.model_copy(
            update={
                "max_turns": min(turns, max_turns or turns),
                "max_tool_calls": tools,
                "max_seconds": seconds,
                "max_usd": usd,
            }
        )

    def why_stopped(self) -> str:
        b, used = self.budget, self.total()
        if used.model_calls >= b.max_turns:
            return f"workflow model-call limit {b.max_turns} reached"
        if used.tool_calls >= b.max_tool_calls:
            return f"workflow tool-call limit {b.max_tool_calls} reached"
        if self.elapsed() >= b.max_seconds:
            return f"workflow time limit {b.max_seconds:.0f}s reached"
        return f"workflow cost above {b.max_usd} USD"

    def charge(self, role: str, **amounts: float | None) -> None:
        """Add measured use to a role. Unknown costs must be passed as worst cases; an
        unknown token count is passed as None and keeps the total unknown."""
        u = self.usage.setdefault(role, RoleUsage())
        for name, value in amounts.items():
            setattr(u, name, _add(getattr(u, name), value))


def _add(total: float | None, value: float | None) -> Any:
    return None if total is None or value is None else total + value
