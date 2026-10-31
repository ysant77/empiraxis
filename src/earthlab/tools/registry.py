"""Allowlisted tool registry: JSON-schema export, argument validation and dispatch.

The model can only name a tool that is registered here. Unknown names and invalid
arguments are rejected with a message the model can act on; nothing is executed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from earthlab.contracts import Strict

MAX_ARGUMENT_BYTES = 8_000


class ToolOutcome(StrEnum):
    EXECUTED = "executed"
    REJECTED = "rejected"
    FAILED = "failed"


class ToolResult(Strict):
    tool: str
    outcome: ToolOutcome
    data: dict[str, Any] | None = None
    error: str | None = None

    def for_model(self) -> str:
        """Compact JSON the model reads back as the tool message."""
        body: dict[str, Any] = {"tool": self.tool, "outcome": self.outcome.value}
        if self.data is not None:
            body["data"] = self.data
        if self.error is not None:
            body["error"] = self.error
        return json.dumps(body, default=str, separators=(",", ":"))


Handler = Callable[[Any], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Handler

    def schema(self) -> dict[str, Any]:
        params = self.args_model.model_json_schema()
        params.pop("title", None)
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": params},
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} already registered")
        self._tools[spec.name] = spec

    def names(self) -> list[str]:
        return sorted(self._tools)

    def only(self, names: frozenset[str]) -> ToolRegistry:
        """A registry with just these tools; any other name is then an unknown tool."""
        scoped = ToolRegistry()
        for name in sorted(names & set(self._tools)):
            scoped.register(self._tools[name])
        return scoped

    def schemas(self) -> list[dict[str, Any]]:
        return [self._tools[name].schema() for name in self.names()]

    def execute(self, name: str, raw_arguments: str) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(tool=name, outcome=ToolOutcome.REJECTED, error="unknown tool")
        args = self._parse(spec, raw_arguments)
        if isinstance(args, ToolResult):
            return args
        try:
            data = spec.handler(args)
        except ValueError as exc:
            return ToolResult(tool=name, outcome=ToolOutcome.FAILED, error=str(exc))
        return ToolResult(tool=name, outcome=ToolOutcome.EXECUTED, data=data)

    @staticmethod
    def _parse(spec: ToolSpec, raw_arguments: str) -> BaseModel | ToolResult:
        if len(raw_arguments.encode()) > MAX_ARGUMENT_BYTES:
            return ToolResult(
                tool=spec.name, outcome=ToolOutcome.REJECTED, error="arguments too large"
            )
        try:
            payload = json.loads(raw_arguments or "{}")
            return spec.args_model.model_validate(payload)
        except json.JSONDecodeError as exc:
            return ToolResult(
                tool=spec.name, outcome=ToolOutcome.REJECTED, error=f"arguments are not JSON: {exc}"
            )
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
                for e in exc.errors()
            )
            return ToolResult(tool=spec.name, outcome=ToolOutcome.REJECTED, error=problems)
