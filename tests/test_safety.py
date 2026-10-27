from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say

from earthlab.agent.loop import RunStatus
from earthlab.llm.types import ProviderError, ProviderErrorKind
from earthlab.metrics import EarthlabMetrics
from earthlab.runtime import Workspace, investigate, new_run_dir, open_workspace
from earthlab.safety.gate import REFUSAL, WITHHELD
from earthlab.safety.llama_guard import LlamaGuard, build_prompt, parse_verdict
from earthlab.safety.scope import answer_out_of_scope, question_out_of_scope

HAZE = {"start": "2015-09-01T00:00", "end": "2015-11-01T00:00"}
CLAIM = {**HAZE, "kind": "peak_region", "region": "west", "value": 471, "statement": "West."}


class FakeCompleter:
    def __init__(self, replies: list[str | ProviderError]):
        self.replies = replies
        self.prompts: list[str] = []

    def complete(self, prompt: str, max_tokens: int) -> str:
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, ProviderError):
            raise reply
        return reply


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def guard(*replies: str | ProviderError) -> LlamaGuard:
    return LlamaGuard(FakeCompleter(list(replies)), "llama-guard-3-8b")


@pytest.mark.parametrize(
    ("question", "fragment"),
    [
        ("Is it safe for my asthmatic child to play outside today?", "advice"),
        ("Which political party should Singapore blame for the haze?", "political"),
        ("Will the haze return next year?", "forecasts"),
    ],
)
def test_out_of_scope_questions(question: str, fragment: str) -> None:
    assert fragment in (question_out_of_scope(question) or "")


def test_answers_negation_is_allowed_assertion_is_not() -> None:
    assert answer_out_of_scope("The data cannot show that fires caused the peak.") is None
    assert answer_out_of_scope("No causal claim is made; west peaked at 471.") is None
    assert "cause" in (answer_out_of_scope("The peak was caused by fires in Sumatra.") or "")
    assert "health" in (answer_out_of_scope("Air was unhealthy; stay indoors.") or "")
    assert "political" in (answer_out_of_scope("The government failed here.") or "")
    assert "forecast" in (answer_out_of_scope("PM2.5 will rise again in 2027.") or "")


def test_parse_llama_guard_replies() -> None:
    assert parse_verdict("safe").safe
    assert parse_verdict("safesafe").safe  # raw mode can repeat without a stop token
    unsafe = parse_verdict("unsafe\nS1,S3")
    assert not unsafe.safe and unsafe.codes == ("S1", "S3")
    assert "Health or Medical Advice" in unsafe.describe()
    assert not parse_verdict("").safe and not parse_verdict("I think this is fine").safe
    assert "unparsed" in parse_verdict("").describe()


def test_prompt_carries_the_earthlab_policy() -> None:
    asked = build_prompt("Which region peaked?")
    assert "S3: Political or Conflict Content." in asked and "'User' messages" in asked
    answered = build_prompt("Which region peaked?", "West.")
    assert "Agent: West." in answered and "ONLY THE LAST Agent message" in answered


def test_refused_question_never_reaches_the_planner(workspace: Workspace, tmp_path: Path) -> None:
    planner = ScriptedClient([call("rank_regions", **HAZE, statistic="max")])
    metrics = EarthlabMetrics()
    run_dir = new_run_dir(tmp_path)
    result = investigate(
        "Should I wear a mask during haze?",
        planner,
        workspace,
        run_dir,
        metrics=metrics,
        guard=guard("unsafe\nS1"),
    )
    assert result.status == RunStatus.REFUSED and result.answer == REFUSAL
    assert planner.requests == [] and result.turns == 0
    assert result.safety[0].blocked_by == "scope_rules"
    assert "S1" in (result.safety[0].guard or "")
    saved = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert saved["status"] == "refused" and saved["safety"][0]["allowed"] is False
    text = metrics.exposition()
    assert (
        'earthlab_safety_checks_total{outcome="blocked",source="scope_rules",stage="question"}'
        in text
    )


def test_llama_guard_alone_can_block_a_question(workspace: Workspace, tmp_path: Path) -> None:
    planner = ScriptedClient([])
    result = investigate(
        "Which region peaked in 2015?",
        planner,
        workspace,
        new_run_dir(tmp_path),
        guard=guard("unsafe\nS7"),
    )
    assert result.status == RunStatus.REFUSED and result.safety[0].blocked_by == "llama_guard"


def test_guard_failure_fails_closed(workspace: Workspace, tmp_path: Path) -> None:
    result = investigate(
        "Which region peaked in 2015?",
        ScriptedClient([]),
        workspace,
        new_run_dir(tmp_path),
        guard=guard(ProviderError(ProviderErrorKind.TRANSPORT, "down")),
    )
    assert result.status == RunStatus.REFUSED
    assert "failing closed" in (result.safety[0].reason or "")


def test_unsafe_final_answer_is_withheld_but_claims_stand(
    workspace: Workspace, tmp_path: Path
) -> None:
    planner = ScriptedClient(
        [call("submit_findings", claims=[CLAIM]), say("West hit 471; people should stay indoors.")]
    )
    result = investigate(
        "Which region peaked?",
        planner,
        workspace,
        new_run_dir(tmp_path),
        guard=guard("safe", "safe"),
    )
    assert result.status == RunStatus.ANSWER_UNVERIFIED and result.answer == WITHHELD
    assert "safety check withheld the text" in result.answer_issues[-1]
    question_check, answer_check = result.safety
    assert question_check.allowed and not answer_check.allowed
    assert answer_check.blocked_by == "scope_rules"
    assert len(result.ledger.supported()) == 1


def test_clean_run_passes_both_gates(workspace: Workspace, tmp_path: Path) -> None:
    planner = ScriptedClient([call("submit_findings", claims=[CLAIM]), say("West peaked at 471.")])
    result = investigate(
        "Which region peaked?",
        planner,
        workspace,
        new_run_dir(tmp_path),
        guard=guard("safe", "safe"),
    )
    assert result.answer == "West peaked at 471." and all(d.allowed for d in result.safety)
    assert result.safety[1].guard == "llama-guard-3-8b: safe"
