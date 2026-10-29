"""The investigation loop: plan, call tools, submit claims, revise on verifier feedback.

With a plan step, the model first submits a typed plan that a deterministic critic
reviews (see plan_step.py). The model chooses every tool call from the allowlist. The
runtime executes, records and limits each call, and only the deterministic verifier
decides whether a claim stands.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from earthlab.agent.area_findings import SUBMIT_AREA_TOOL, AreaLedger
from earthlab.agent.budget import Budget, BudgetMeter, BudgetStop, prompt_bytes
from earthlab.agent.findings import SUBMIT_TOOL, FindingsLedger
from earthlab.agent.limitations import DECLARE_TOOL, LimitationArgs, LimitationLog
from earthlab.agent.plan_step import PlanStep
from earthlab.agent.prompts import (
    FINAL_AFTER_LIMITATION,
    FINAL_ANSWER,
    NUDGE_SUBMIT,
    REVISE_ANSWER,
    system_prompt,
)
from earthlab.agent.rendered import render_answer
from earthlab.llm.client import ChatClient
from earthlab.llm.types import ChatResponse, ProviderError, ToolCall
from earthlab.metrics import EarthlabMetrics
from earthlab.planning.report import CriticReport
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
    ABSTAINED = "abstained"
    NO_SUPPORTED_FINDINGS = "no_supported_findings"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PROVIDER_ERROR = "provider_error"
    REFUSED = "refused"


PLANNER_TEMPERATURE = 1.0  # matches the Muse sampling card; recorded in every bench run
_ANSWERED = (RunStatus.VERIFIED, RunStatus.PARTIAL, RunStatus.ABSTAINED)


@dataclass
class RunState:
    messages: list[dict[str, Any]]
    answer: str = ""
    nudged: bool = False
    finalising: bool = False
    stop_reason: str = ""
    revision_note: str | None = None
    rendered: bool = False
    skipped_tool_calls: int = 0
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
    skipped_tool_calls: int = 0
    limitations: tuple[LimitationArgs, ...] = ()
    area_ledger: AreaLedger = field(default_factory=AreaLedger)
    plan_reviews: tuple[CriticReport, ...] = ()
    answer_source: str = "model"


_SUBMIT_TOOLS = (SUBMIT_TOOL, SUBMIT_AREA_TOOL)


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
        clock: Callable[[], float] = time.monotonic,
        limitations: LimitationLog | None = None,
        area_ledger: AreaLedger | None = None,
        plan_step: PlanStep | None = None,
        render_fallback: bool = False,
    ):
        self._client = client
        self._registry = registry
        self._ledger = ledger
        self._metrics = metrics
        self._trace = trace
        self._meter = BudgetMeter(budget or Budget(), clock)
        self._reasoning = reasoning
        self._answer_gate = answer_gate
        self._limitations = limitations or LimitationLog()
        self._area = area_ledger or AreaLedger()
        self._plan = plan_step
        self._render_fallback = render_fallback

    def run(self, question: str) -> Investigation:
        cfg = self._client.config
        if self._plan is not None:
            self._plan.question = question
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
                {
                    "role": "system",
                    "content": system_prompt(self._reasoning, self._plan is not None),
                },
                {"role": "user", "content": question},
            ]
        )
        self._metrics.active.inc()
        try:
            status = self._loop(state)
            audit = self._checked_answer(question, state, status)
        finally:
            self._metrics.active.dec()
        decision = self._gate_answer(question, state)
        issues = _answer_issues(audit, decision, state)
        if status in _ANSWERED and not state.answer:
            issues = ("no final text was produced", *issues)
        if issues and status in _ANSWERED:
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

    def _revise_answer(self, question: str, state: RunState, audit: AnswerAudit) -> AnswerAudit:
        """Give the model one text-only chance to fix a failed text, then check it again.

        A failed or empty revision keeps the original text and its issues.
        """
        if self._meter.exhausted() is not None:
            return audit
        self._trace.append("answer_revision", "verifier", issues=audit.problems())
        issues = "\n".join(f"- {issue}" for issue in audit.problems())
        state.messages.append({"role": "user", "content": REVISE_ANSWER.format(issues=issues)})
        state.finalising = True  # tool_choice "none": a revision can never run a tool
        try:
            resp = self._call_model(state)
        except BudgetStop as exc:
            state.revision_note = f"revision not run: {exc}"
            return audit
        except ProviderError as exc:
            state.revision_note = f"revision failed: {exc.kind.value}"
            return audit
        state.messages.append(_assistant_message(resp))
        revised = resp.content.strip()
        if not revised:
            state.revision_note = "revision returned no text"
            return audit
        state.answer = revised
        return self._audit_answer(state) or audit

    def _checked_answer(
        self, question: str, state: RunState, status: RunStatus
    ) -> AnswerAudit | None:
        """Audit the text; on failure revise once, then fall back to a rendered answer."""
        audit = self._audit_answer(state)
        if audit is not None and not audit.passed and status in _ANSWERED:
            audit = self._revise_answer(question, state, audit)
            if not audit.passed and self._render_fallback:
                self._render_answer(state)
        return audit

    def _render_answer(self, state: RunState) -> None:
        """Replace a text that still fails the audit with one built from verified findings.

        Without any verified finding or limitation, the failed text and its issues stay.
        """
        text = render_answer(self._ledger, self._area, self._limitations.entries)
        if text is None:
            return
        self._trace.append("answer_rendered", "runtime", withheld_text=state.answer)
        state.answer = text
        state.rendered = True

    def _audit_answer(self, state: RunState) -> AnswerAudit | None:
        if not state.answer:
            return None
        area_ok = {i for i, r in self._area.latest_by_id().items() if r in self._area.supported()}
        audit = audit_answer(state.answer, self._ledger.latest_by_id(), area_ok)
        outcome = "supported" if audit.passed else "unsupported"
        self._metrics.record_verification(Check.ANSWER.value, outcome)
        self._trace.append("answer_audit", "verifier", **audit.model_dump(mode="json"))
        return audit

    def _loop(self, state: RunState) -> RunStatus:
        while True:
            if (limit := self._meter.exhausted()) is not None:
                state.stop_reason = limit
                return self._status_after_stop(budget_hit=True)
            try:
                resp = self._call_model(state)
            except BudgetStop as exc:
                state.stop_reason = str(exc)
                return self._status_after_stop(budget_hit=True)
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
        if state.finalising or self._ledger.rounds or self._area.rounds:
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
        """Reserve the worst-case cost and check every limit, then call the model.

        Raises BudgetStop, without calling, when the call could cross a limit.
        """
        cfg = self._client.config
        schemas = self._registry.schemas()
        worst = self._meter.reserve_model_call(cfg, prompt_bytes(state.messages, schemas))
        # Keep the same tool schemas on the final turn so the server can reuse its prompt cache.
        tool_choice = "none" if state.finalising else "auto"
        try:
            resp = self._client.chat(
                state.messages,
                schemas,
                max_tokens=self._meter.budget.max_output_tokens,
                temperature=PLANNER_TEMPERATURE,
                tool_choice=tool_choice,
                timeout=min(cfg.timeout_seconds, self._meter.remaining_seconds()),
            )
        except ProviderError as exc:
            self._metrics.record_inference(cfg.name, cfg.logical_model, exc.kind.value, None)
            self._trace.append("model_error", "runtime", kind=exc.kind.value)
            raise
        self._account(state, resp, worst)
        return resp

    def _account(self, state: RunState, resp: ChatResponse, worst: float) -> None:
        cfg = self._client.config
        usage = resp.usage
        charged = self._meter.settle_model_call(cfg, usage, worst)
        cost = cfg.estimate_cost_usd(usage.prompt_tokens, usage.completion_tokens)
        cost = charged if cost is None and charged > 0 else cost
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
        """Check the limits before each call in the batch; skip, never run, the rest."""
        for call in calls:
            self._metrics.record_tool(call.name, "requested")
            reason = None if self._plan is None else self._plan.refusal(call.name)
            reason = reason or self._meter.check_tool_call(call.name in _SUBMIT_TOOLS)
            if reason is not None:
                self._skip_tool_call(state, call, reason)
                continue
            self._meter.tool_calls += 1
            result = self._registry.execute(call.name, call.arguments)
            if call.name in _SUBMIT_TOOLS and result.outcome is ToolOutcome.EXECUTED:
                self._meter.submissions += 1
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
            if call.name in _SUBMIT_TOOLS and result.outcome is ToolOutcome.EXECUTED:
                self._after_submission(state, call.name)
            if call.name == DECLARE_TOOL and result.outcome is ToolOutcome.EXECUTED:
                state.finalising = True
                state.stop_reason = state.stop_reason or "limitation declared"
                state.messages.append({"role": "user", "content": FINAL_AFTER_LIMITATION})

    def _skip_tool_call(self, state: RunState, call: ToolCall, reason: str) -> None:
        self._metrics.record_tool(call.name, "skipped")
        self._trace.append("tool_skipped", "runtime", name=call.name, reason=reason)
        state.skipped_tool_calls += 1
        state.messages.append(
            {"role": "tool", "tool_call_id": call.id, "content": f"not run: {reason}"}
        )

    def _all_supported(self) -> bool:
        """Every ledger with submissions is fully supported, and at least one has some."""
        used = [led for led in (self._ledger, self._area) if led.rounds]
        return bool(used) and all(led.all_supported() for led in used)

    def _after_submission(self, state: RunState, tool: str) -> None:
        latest = self._ledger.latest if tool == SUBMIT_TOOL else self._area.latest
        for verdict in latest:
            self._metrics.record_verification(verdict.check.value, verdict.verdict.value)
        if self._all_supported():
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
        if self._limitations.entries:
            return RunStatus.ABSTAINED
        if self._all_supported():
            return RunStatus.VERIFIED
        if self._ledger.supported() or self._area.supported():
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
            skipped_tool_calls=state.skipped_tool_calls,
            limitations=tuple(self._limitations.entries),
            area_ledger=self._area,
            plan_reviews=() if self._plan is None else tuple(self._plan.reviews),
            answer_source="rendered" if state.rendered else "model",
        )


def _answer_issues(
    audit: AnswerAudit | None, decision: SafetyDecision | None, state: RunState
) -> tuple[str, ...]:
    """Why the final text cannot be called verified; empty when it can."""
    issues = [] if audit is None or state.rendered else audit.problems()
    if state.revision_note is not None and issues:
        issues.append(state.revision_note)
    if decision is not None and not decision.allowed:
        issues.append(f"safety check withheld the text: {decision.reason}")
    return tuple(issues)
