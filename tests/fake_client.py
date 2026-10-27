"""A scripted ChatClient for agent tests. Records every request it receives."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from earthlab.llm.providers import ProviderConfig
from earthlab.llm.types import ChatResponse, ProviderError, ToolCall, Usage

FAKE_CONFIG = ProviderConfig(
    name="fake-glimmer",
    kind="local",
    base_url="http://127.0.0.1:9/v1",
    model="muse-glimmer-30B",
    logical_model="muse-glimmer-30b",
    usd_per_mtok_input=0.0,
    usd_per_mtok_output=0.0,
)

Step = tuple[str, list[tuple[str, dict[str, Any]]]] | ProviderError


def say(text: str) -> Step:
    return (text, [])


def call(name: str, **arguments: Any) -> Step:
    return ("", [(name, arguments)])


class ScriptedClient:
    def __init__(self, steps: Sequence[Step], config: ProviderConfig = FAKE_CONFIG):
        self.config = config
        self._steps = list(steps)
        self.requests: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
        tool_choice: str = "auto",
    ) -> ChatResponse:
        self.requests.append(
            {"messages": list(messages), "tools": tools, "tool_choice": tool_choice}
        )
        step = self._steps.pop(0) if self._steps else ("done", [])
        if isinstance(step, ProviderError):
            raise step
        text, calls = step
        return ChatResponse(
            provider=self.config.name,
            model=self.config.model,
            served_model="muse-glimmer-30B",
            request_id=f"req-{len(self.requests)}",
            content=text,
            reasoning="plan",
            tool_calls=tuple(
                ToolCall(id=f"c{len(self.requests)}{i}", name=n, arguments=json.dumps(a))
                for i, (n, a) in enumerate(calls)
            ),
            finish_reason="tool_calls" if calls else "stop",
            usage=Usage(prompt_tokens=100, completion_tokens=10),
            wall_seconds=0.01,
        )
