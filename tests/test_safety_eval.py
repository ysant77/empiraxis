from __future__ import annotations

from pathlib import Path

import pytest

from earthlab import cli
from earthlab.evals.safety import load_cases, run_case, summarize
from earthlab.llm.types import ProviderError, ProviderErrorKind
from earthlab.safety.llama_guard import LlamaGuard

CASES = Path(__file__).resolve().parents[1] / "evals" / "safety_cases.yaml"


class AlwaysSafe:
    def complete(self, prompt: str, max_tokens: int) -> str:
        return "safe"


class Down:
    def complete(self, prompt: str, max_tokens: int) -> str:
        raise ProviderError(ProviderErrorKind.TRANSPORT, "down")


def test_rules_alone_meet_every_label() -> None:
    results = [run_case(case, None) for case in load_cases(CASES)]
    summary = summarize(results)
    assert summary["scope_rules"] == f"{len(results)}/{len(results)}"
    assert summary["llama_guard"] == "0/0" and summary["unsafe_allowed_by_gate"] == "0"


def test_a_permissive_guard_cannot_weaken_the_gate() -> None:
    results = [run_case(c, LlamaGuard(AlwaysSafe(), "g")) for c in load_cases(CASES)]
    assert summarize(results)["unsafe_allowed_by_gate"] == "0"


def test_unreachable_guard_counts_as_block() -> None:
    case = load_cases(CASES)[0]
    result = run_case(case, LlamaGuard(Down(), "g"))
    assert result.guard_allows is False and not result.gate_allows


def test_safety_eval_command_without_guard(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["safety-eval", "--cases", str(CASES), "--guard", "none"]) == 0
    out = capsys.readouterr().out
    assert "q-asthma-exercise" in out and '"combined_gate"' in out
