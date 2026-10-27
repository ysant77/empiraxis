"""The investigation loop: plan, call tools, submit claims, revise on verifier feedback.

The model chooses every tool call from the allowlist. The runtime executes, records and
limits each call, and only the deterministic verifier decides whether a claim stands.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from earthlab.agent.budget import Budget, BudgetMeter
from earthlab.agent.findings import SUBMIT_TOOL, FindingsLedger
from earthlab.agent.prompts import FINAL_ANSWER, NUDGE_SUBMIT, system_prompt
from earthlab.llm.client import ChatClient
from earthlab.llm.types import ChatResponse, ProviderError, ToolCall
from earthlab.metrics import EarthlabMetrics
from earthlab.safety.gate import WITHHELD, SafetyDecision
from earthlab.tools.registry import ToolOutcome, ToolRegistry
from earthlab.trace import RunTrace
from earthlab.verify.answer_audit import AnswerAudit, audit_answer
from earthlab.verify.claims import Check

AnswerGate = Callable[[str, str], SafetyDecision]


class RunStatus(StrEnum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    ANSWER_UNVERIFIED = "answer_unverified"
    NO_SUPPORTED_FINDINGS = "no_supported_findings"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PROVIDER_ERROR = "provider_error"
    REFUSED = "refused"


@dataclass
class RunState:
    messages: list[dict[str, Any]]
    answer: str = ""
    nudged: bool = False
    finalising: bool = False
    stop_reason: str = ""
    served_model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    evidence: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class Investigation:
    status: RunStatus
    stop_reason: str
    answer: str
    ledger: FindingsLedger
    turns: int
    tool_calls: int
    submissions: int
    seconds: float
    cost_usd: float | None
    provider: str
    model: str
    served_model: str | None
    prompt_tokens: int
    completion_tokens: int
    answer_audit: AnswerAudit | None = None
    safety: tuple[SafetyDecision, ...] = ()
    answer_issues: tuple[str, ...] = ()


def _assistant_message(resp: ChatResponse) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": resp.content}
    if resp.tool_calls:
        message["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in resp.tool_calls
        ]
    return message


class Investigator:
    def __init__(
        self,
        client: ChatClient,
        registry: ToolRegistry,
        ledger: FindingsLedger,
        *,
        metrics: EarthlabMetrics,
        trace: RunTrace,
        budget: Budget | None = None,
        reasoning: str = "medium",
        answer_gate: AnswerGate | None = None,
    ):
        self._client = client
        self._registry = registry
        self._ledger = ledger
        self._metrics = metrics
        self._trace = trace
        self._meter = BudgetMeter(budget or Budget())
        self._reasoning = reasoning
        self._answer_gate = answer_gate

    def run(self, question: str) -> Investigation:
        cfg = self._client.config
        self._trace.append(
            "start",
            "runtime",
            question=question,
            provider=cfg.name,
            model=cfg.model,
            logical_model=cfg.logical_model,
            budget=self._meter.budget.model_dump(),
        )
        state = RunState(
            messages=[
                {"role": "system", "content": system_prompt(self._reasoning)},
                {"role": "user", "content": question},
            ]
        )
        self._metrics.active.inc()
        try:
            status = self._loop(state)
        finally:
            self._metrics.active.dec()
        audit = self._audit_answer(question, state)
        decision = self._gate_answer(question, state)
        issues = _answer_issues(audit, decision)
        if issues and status in (RunStatus.VERIFIED, RunStatus.PARTIAL):
            status = RunStatus.ANSWER_UNVERIFIED
        self._metrics.investigations.labels(status.value).inc()
        result = self._result(status, state, audit, decision, issues)
        self._trace.append(
            "finish",
            "runtime",
            status=status.value,
            reason=state.stop_reason,
            answer=state.answer,
            answer_issues=list(issues),
            turns=result.turns,
            cost_usd=result.cost_usd,
        )
        return result

    def _gate_answer(self, question: str, state: RunState) -> SafetyDecision | None:
        """Run the safety gate on the final text; a blocked text is replaced, never shown."""
        if self._answer_gate is None or not state.answer:
            return None
        decision = self._answer_gate(question, state.answer)
        if not decision.allowed:
            state.answer = WITHHELD
        return decision

    def _audit_answer(self, question: str, state: RunState) -> AnswerAudit | None:
        if not state.answer:
            return None
        audit = audit_answer(state.answer, self._ledger.supported(), question)
        outcome = "supported" if audit.passed else "unsupported"
        self._metrics.record_verification(Check.ANSWER.value, outcome)
        self._trace.append(
            "answer_audit",
            "verifier",
            numbers_checked=audit.numbers_checked,
            ungrounded=list(audit.ungrounded),
            misattributed=list(audit.misattributed),
            language=audit.language,
        )
        return audit

    def _loop(self, state: RunState) -> RunStatus:
        while True:
            if (limit := self._meter.exhausted()) is not None:
                state.stop_reason = limit
                return self._status_after_stop(budget_hit=True)
            try:
                resp = self._call_model(state)
            except ProviderError as exc:
                state.stop_reason = str(exc)
                return RunStatus.PROVIDER_ERROR
            state.messages.append(_assistant_message(resp))
            if state.finalising or not resp.tool_calls:
                if self._settle_text_turn(state, resp):
                    return self._status_after_stop(budget_hit=False)
                continue
            self._run_tool_calls(state, resp.tool_calls)

    def _settle_text_turn(self, state: RunState, resp: ChatResponse) -> bool:
        """Return True when the run should end after a turn without tool calls."""
        if state.finalising or self._ledger.rounds:
            state.answer = resp.content.strip()
            state.stop_reason = state.stop_reason or "final answer given"
            return True
        if state.nudged:
            state.stop_reason = "model answered without submitting claims"
            return True
        state.nudged = True
        state.messages.append({"role": "user", "content": NUDGE_SUBMIT})
        return False

    def _call_model(self, state: RunState) -> ChatResponse:
        cfg = self._client.config
        self._meter.turns += 1
        # Keep the same tool schemas on the final turn so the server can reuse its prompt cache.
        tool_choice = "none" if state.finalising else "auto"
        try:
            resp = self._client.chat(
                state.messages,
                self._registry.schemas(),
                max_tokens=self._meter.budget.max_output_tokens,
                temperature=1.0,
                tool_choice=tool_choice,
            )
        except ProviderError as exc:
            self._metrics.record_inference(cfg.name, cfg.logical_model, exc.kind.value, 0.0)
            self._trace.append("model_error", "runtime", kind=exc.kind.value)
            raise
        self._account(state, resp)
        return resp

    def _account(self, state: RunState, resp: ChatResponse) -> None:
        cfg = self._client.config
        usage = resp.usage
        cost = cfg.estimate_cost_usd(usage.prompt_tokens, usage.completion_tokens)
        self._meter.cost_usd += cost or 0.0
        state.prompt_tokens += usage.prompt_tokens or 0
        state.completion_tokens += usage.completion_tokens or 0
        state.served_model = resp.served_model or state.served_model
        self._metrics.record_inference(
            cfg.name,
            cfg.logical_model,
            "ok",
            resp.wall_seconds,
            (usage.prompt_tokens, usage.completion_tokens),
            cost,
        )
        self._trace.append(
            "model_turn",
            "model",
            turn=self._meter.turns,
            request_id=resp.request_id,
            served_model=resp.served_model,
            content=resp.content,
            reasoning=resp.reasoning,
            tool_calls=[c.model_dump() for c in resp.tool_calls],
            usage=usage.model_dump(),
            wall_seconds=round(resp.wall_seconds, 3),
        )

    def _run_tool_calls(self, state: RunState, calls: tuple[ToolCall, ...]) -> None:
        for call in calls:
            self._meter.tool_calls += 1
            self._metrics.record_tool(call.name, "requested")
            if call.name == SUBMIT_TOOL:
                self._meter.submissions += 1
            result = self._registry.execute(call.name, call.arguments)
            self._metrics.record_tool(call.name, result.outcome.value)
            if result.data is not None:
                state.evidence.append(result.data)
            self._trace.append(
                "tool_result",
                "runtime",
                name=call.name,
                arguments=call.arguments,
                outcome=result.outcome.value,
                error=result.error,
                data=result.data,
            )
            state.messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result.for_model()}
            )
            if call.name == SUBMIT_TOOL and result.outcome is ToolOutcome.EXECUTED:
                self._after_submission(state)

    def _after_submission(self, state: RunState) -> None:
        for verdict in self._ledger.latest:
            self._metrics.record_verification(verdict.check.value, verdict.verdict.value)
        if self._ledger.all_supported():
            state.finalising = True
            state.messages.append({"role": "user", "content": FINAL_ANSWER})
        elif self._meter.submissions >= self._meter.budget.max_submissions:
            state.finalising = True
            state.stop_reason = "submission limit reached"
            state.messages.append(
                {
                    "role": "user",
                    "content": FINAL_ANSWER.replace(
                        "All submitted claims are supported",
                        "No more submissions are allowed; report only the supported claims",
                    ),
                }
            )

    def _status_after_stop(self, *, budget_hit: bool) -> RunStatus:
        if self._ledger.all_supported():
            return RunStatus.VERIFIED
        if self._ledger.supported():
            return RunStatus.PARTIAL
        return RunStatus.BUDGET_EXHAUSTED if budget_hit else RunStatus.NO_SUPPORTED_FINDINGS

    def _result(
        self,
        status: RunStatus,
        state: RunState,
        audit: AnswerAudit | None,
        decision: SafetyDecision | None,
        issues: tuple[str, ...],
    ) -> Investigation:
        cfg = self._client.config
        priced = cfg.usd_per_mtok_input is not None and cfg.usd_per_mtok_output is not None
        return Investigation(
            status=status,
            stop_reason=state.stop_reason,
            answer=state.answer,
            ledger=self._ledger,
            turns=self._meter.turns,
            tool_calls=self._meter.tool_calls,
            submissions=self._meter.submissions,
            seconds=round(self._meter.elapsed(), 3),
            cost_usd=round(self._meter.cost_usd, 6) if priced else None,
            provider=cfg.name,
            model=cfg.model,
            served_model=state.served_model,
            prompt_tokens=state.prompt_tokens,
            completion_tokens=state.completion_tokens,
            answer_audit=audit,
            safety=() if decision is None else (decision,),
            answer_issues=issues,
        )


def _answer_issues(audit: AnswerAudit | None, decision: SafetyDecision | None) -> tuple[str, ...]:
    """Why the final text cannot be called verified; empty when it can."""
    issues = [] if audit is None else audit.problems()
    if decision is not None and not decision.allowed:
        issues.append(f"safety check withheld the text: {decision.reason}")
    return tuple(issues)
