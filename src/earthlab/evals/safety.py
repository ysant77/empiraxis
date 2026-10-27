"""Score the safety gate on labelled cases: Llama Guard alone, rules alone, and both."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from earthlab.contracts import Strict
from earthlab.llm.types import ProviderError
from earthlab.safety.llama_guard import LlamaGuard
from earthlab.safety.scope import answer_out_of_scope, question_out_of_scope


class SafetyCase(Strict):
    id: str
    question: str
    answer: str | None = None
    allowed: bool


class CaseResult(Strict):
    case: SafetyCase
    guard_allows: bool | None
    rules_allow: bool

    @property
    def gate_allows(self) -> bool:
        return self.rules_allow and self.guard_allows is not False


def load_cases(path: Path) -> list[SafetyCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [SafetyCase.model_validate(item) for item in raw["cases"]]


def run_case(case: SafetyCase, guard: LlamaGuard | None) -> CaseResult:
    if case.answer is None:
        rules_allow = question_out_of_scope(case.question) is None
    else:
        rules_allow = answer_out_of_scope(case.answer) is None
    guard_allows: bool | None = None
    if guard is not None:
        try:
            guard_allows = guard.classify(case.question, case.answer).safe
        except ProviderError:
            guard_allows = False  # the gate fails closed
    return CaseResult(case=case, guard_allows=guard_allows, rules_allow=rules_allow)


def _correct(results: list[CaseResult], pick: Any) -> str:
    rows = [r for r in results if pick(r) is not None]
    hits = sum(1 for r in rows if pick(r) == r.case.allowed)
    return f"{hits}/{len(rows)}"


def summarize(results: list[CaseResult]) -> dict[str, str]:
    return {
        "llama_guard": _correct(results, lambda r: r.guard_allows),
        "scope_rules": _correct(results, lambda r: r.rules_allow),
        "combined_gate": _correct(results, lambda r: r.gate_allows),
        "unsafe_allowed_by_gate": str(
            sum(1 for r in results if r.gate_allows and not r.case.allowed)
        ),
        "safe_blocked_by_gate": str(
            sum(1 for r in results if not r.gate_allows and r.case.allowed)
        ),
    }
