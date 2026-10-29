"""Safety gate for the question (before any model runs) and the final answer.

Two independent checks, either of which can block: deterministic scope rules and, when
configured, Meta Llama Guard. If the safety model is configured but fails, the gate
fails closed.
"""

from __future__ import annotations

from enum import StrEnum

from earthlab.contracts import Strict
from earthlab.llm.types import ProviderError
from earthlab.metrics import EarthlabMetrics
from earthlab.safety.llama_guard import LlamaGuard
from earthlab.safety.scope import answer_out_of_scope, question_out_of_scope
from earthlab.trace import RunTrace

REFUSAL = (
    "EarthLab studies past air-quality observations. It does not give health or safety "
    "advice, take political positions or make forecasts, so it cannot answer this question. "
    "Try a question about what the NEA PM2.5 data recorded, for example which region had "
    "the highest hourly value in October 2015."
)
WITHHELD = (
    "The final summary was withheld by the safety check. The verified claims in this report "
    "still stand; read them in the claims table."
)


CAUSAL_CODE = "S5"
CAUSAL_ABSTENTION = (
    "The question asks what caused an observation. The pinned observations alone cannot "
    "identify a cause, so EarthLab does not attribute one. It can describe what the data "
    "recorded and when, as a temporal association."
)


class Stage(StrEnum):
    QUESTION = "question"
    ANSWER = "answer"


class SafetyDecision(Strict):
    stage: Stage
    allowed: bool
    blocked_by: str | None = None
    reason: str | None = None
    guard: str | None = None
    guard_codes: tuple[str, ...] = ()

    def causal_only(self) -> bool:
        """True for a question that Llama Guard blocked for S5 (causal attribution) alone.

        Such a question is routed to a causation_not_identifiable abstention instead of a
        refusal. Every other category, and every answer-stage block, stays a block.
        """
        return (
            self.stage is Stage.QUESTION
            and self.blocked_by == "llama_guard"
            and self.guard_codes == (CAUSAL_CODE,)
        )


class SafetyGate:
    def __init__(self, guard: LlamaGuard | None, metrics: EarthlabMetrics, trace: RunTrace):
        self._guard = guard
        self._metrics = metrics
        self._trace = trace

    def check_question(self, question: str) -> SafetyDecision:
        return self._decide(Stage.QUESTION, question_out_of_scope(question), question, None)

    def check_answer(self, question: str, answer: str) -> SafetyDecision:
        return self._decide(Stage.ANSWER, answer_out_of_scope(answer), question, answer)

    def _decide(
        self, stage: Stage, rule_reason: str | None, question: str, answer: str | None
    ) -> SafetyDecision:
        guard_text, guard_block, codes = self._run_guard(question, answer)
        if rule_reason is not None:
            decision = SafetyDecision(
                stage=stage,
                allowed=False,
                blocked_by="scope_rules",
                reason=rule_reason,
                guard=guard_text,
            )
        elif guard_block is not None:
            decision = SafetyDecision(
                stage=stage,
                allowed=False,
                blocked_by="llama_guard",
                reason=guard_block,
                guard=guard_text,
                guard_codes=codes,
            )
        else:
            decision = SafetyDecision(stage=stage, allowed=True, guard=guard_text)
        self._record(decision)
        return decision

    def _run_guard(
        self, question: str, answer: str | None
    ) -> tuple[str | None, str | None, tuple[str, ...]]:
        """Return (guard description, blocking reason or None, flagged category codes)."""
        if self._guard is None:
            return None, None, ()
        try:
            verdict = self._guard.classify(question, answer)
        except ProviderError as exc:
            return f"error: {exc.kind.value}", "safety model unavailable; failing closed", ()
        text = f"{self._guard.name}: {verdict.describe()}"
        if verdict.safe:
            return text, None, ()
        return text, f"Llama Guard flagged {verdict.describe()}", verdict.codes

    def _record(self, decision: SafetyDecision) -> None:
        outcome = "allowed" if decision.allowed else "blocked"
        source = decision.blocked_by or ("llama_guard" if self._guard else "scope_rules")
        self._metrics.record_safety(decision.stage.value, source, outcome)
        self._trace.append("safety_check", "safety", **decision.model_dump(mode="json"))
