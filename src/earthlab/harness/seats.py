"""The roles of one run: bounded model calls, tool loops and handoffs, all on one trace.

A model proposes inside a schema and code checks the result. Every experiment shares this.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from earthlab.agent.budget import Budget, BudgetMeter, BudgetStop
from earthlab.agent.messages import assistant_message
from earthlab.digest import payload_digest
from earthlab.llm.client import ChatClient
from earthlab.llm.types import ToolCall
from earthlab.metrics import EarthlabMetrics
from earthlab.team.delegate import tool_schema
from earthlab.trace import RunTrace
from earthlab.workflow.calls import RoleCalls
from earthlab.workflow.ledger import WorkflowLedger


class Stopped(Exception):
    """A role gave no usable proposal inside its calls. The run ends without a result."""


@dataclass
class ArmLog:
    arm: str
    started: float = field(default_factory=time.perf_counter)
    training_seconds: float = 0.0
    tools: int = 0
    rejected: int = 0
    peak_rss_mb: float = 0.0


def _not_on_ticket(_args: str) -> dict[str, Any]:
    raise ValueError("this tool is not on the ticket")


class Seats:
    def __init__(self, arm: str, run_dir: Path, client: ChatClient | None, brief: Any):
        self.log, self.run_dir, self.brief = ArmLog(arm), run_dir, brief
        self.trace = RunTrace(run_dir / "trace.jsonl")
        self.ledger = WorkflowLedger(Budget(max_turns=40, max_tool_calls=40, max_seconds=5400.0))
        self.client = client
        self.calls: dict[str, RoleCalls] = {}
        self.root = f"{run_dir.name.lower()}.pm"
        self.lead_task = f"{self.root}.lead"

    def role(self, name: str) -> RoleCalls:
        if self.client is None:
            raise Stopped("the deterministic arm has no model")
        if name not in self.calls:
            metrics = EarthlabMetrics()
            self.calls[name] = RoleCalls(name, self.client, self.trace, metrics, self.ledger)
        return self.calls[name]

    def _meter(self, turns: int) -> BudgetMeter:
        stage = self.ledger.stage(turns)
        if stage is None:
            raise BudgetStop(self.ledger.why_stopped())
        return BudgetMeter(stage)

    def propose[T: BaseModel](
        self, role: str, system: str, user: Any, name: str, model: type[T],
        check: Callable[[T], list[str]] | None = None,
    ) -> T:  # fmt: skip
        """One schema-only call and one correction. Code checks the result."""
        tool = tool_schema(name, f"Submit {name}.", model)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, default=str)},
        ]
        issues = ["no proposal was submitted"]
        meter = self._meter(2)
        for _ in range(2):
            resp = self.role(role).call(meter, messages, [tool], "auto")
            messages.append(assistant_message(resp))
            call = next((c for c in resp.tool_calls if c.name == name), None)
            if call is None:
                issues = [f"call {name}"]
                messages.append({"role": "user", "content": issues[0]})
                continue
            try:
                value = model.model_validate_json(call.arguments)
                issues = check(value) if check else []
            except ValidationError as exc:
                issues = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()][:5]
                value = None
            self.trace.append(
                "proposal_reviewed", "runtime", role=role, tool=name, valid=not issues,
                issues=issues, proposal=None if value is None else value.model_dump(mode="json"),
            )  # fmt: skip
            if value is not None and not issues:
                return value
            body = json.dumps({"issues": issues})
            messages.extend(
                {"role": "tool", "tool_call_id": c.id, "content": body} for c in resp.tool_calls
            )
        raise Stopped(f"{name}: {'; '.join(issues)}")

    def tool(self, call: ToolCall, handler: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
        self.log.tools += 1
        try:
            body = handler(call.arguments)
        except (ValidationError, ValueError) as exc:
            self.log.rejected += 1
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
            self.trace.append(
                "tool_result", "runtime", name=call.name, outcome="rejected", error=error,
                arguments=call.arguments, data={},
            )  # fmt: skip
            return {"error": error}
        refs = {k: v for k, v in body.items() if k in ("sha256", "features_id", "model_id")}
        self.trace.append(
            "tool_result", "runtime", name=call.name, outcome="executed", error=None,
            arguments=call.arguments, data=refs,
        )  # fmt: skip
        return body

    def loop(
        self, role: str, system: str, ticket: dict[str, Any], turns: int,
        tools: dict[str, tuple[type[BaseModel], Callable[[str], dict[str, Any]]]],
        finish: str, finish_model: type[BaseModel],
    ) -> str:  # fmt: skip
        """A bounded tool loop. It returns the arguments of the closing submission."""
        schemas = [tool_schema(n, f"Call {n}.", m) for n, (m, _) in tools.items()]
        schemas.append(tool_schema(finish, f"Call {finish}.", finish_model))
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(ticket, default=str)},
        ]
        meter = self._meter(turns)
        for _ in range(turns):
            resp = self.role(role).call(meter, messages, schemas, "auto")
            messages.append(assistant_message(resp))
            for call in resp.tool_calls:
                if call.name == finish:
                    return call.arguments
                entry = tools.get(call.name)
                if entry is None:
                    body = self.tool(call, _not_on_ticket)
                else:
                    body = self.tool(call, entry[1])
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(body)}
                )
            if not resp.tool_calls:
                raise Stopped(f"{role} stopped without {finish}")
        raise Stopped(f"{role} used its turns without {finish}")

    def invoke(self, phase: str, role: str, task: str, status: str | None = None) -> None:
        data: dict[str, Any] = {"phase": phase, "role": role, "task_id": task}
        if phase == "finished":
            data |= {"status": status, "model_calls": self.role_turns(role)}
        self.trace.append("role_invocation", "runtime", **data)

    def role_turns(self, role: str) -> int:
        """Model calls this role made so far in the run, from the trace."""
        turns = (e["data"] for e in self.trace.records() if e["event"] == "model_turn")
        return sum(t["role"] == role for t in turns)

    def handoff(self, task: str, parent: str, receiver: str, ticket: dict[str, Any]) -> None:
        self.trace.append(
            "task_handoff", "runtime", task_id=task, parent_task_id=parent, receiver=receiver,
            brief_sha256=payload_digest(self.brief), task_sha256=payload_digest(ticket),
            task=ticket,
        )  # fmt: skip


def usage(seats: Seats) -> dict[str, Any]:
    total, entries = seats.ledger.total(), list(seats.trace.records())
    turns = [e["data"] for e in entries if e["event"] == "model_turn"]
    return {
        "wall_seconds": round(time.perf_counter() - seats.log.started, 1),
        "inference_seconds": round(sum(float(t["wall_seconds"]) for t in turns), 1),
        "training_seconds": round(seats.log.training_seconds, 1),
        "peak_training_rss_mb": seats.log.peak_rss_mb,
        "model_calls": total.model_calls,
        "prompt_tokens": total.prompt_tokens,
        "completion_tokens": total.completion_tokens,
        "cached_tokens": "not exposed by this provider",
        "retries": sum(e["event"] == "model_retry_skipped" for e in entries),
        "provider_faults": sum(e["event"] == "model_error" for e in entries),
        "tool_calls": seats.log.tools,
        "rejected_tool_calls": seats.log.rejected,
        "human_interventions": 0,
    }
