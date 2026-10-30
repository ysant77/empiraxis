"""Answer binding and the S5-only guard route.

The final text may state only values from verified findings. A causal-attribution
question that Llama Guard blocks for S5 alone becomes a typed abstention; every other
category, and every answer-stage block, is unchanged. Development cases only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say

from earthlab.agent.area_findings import AreaLedger
from earthlab.agent.findings import FindingsLedger
from earthlab.agent.loop import RunStatus
from earthlab.agent.rendered import render_answer
from earthlab.events.adapter import load_run
from earthlab.runtime import RunOptions, Workspace, investigate, open_workspace
from earthlab.safety.gate import CAUSAL_ABSTENTION, SafetyDecision, Stage
from earthlab.safety.llama_guard import LlamaGuard

RENDER = RunOptions(render_fallback=True)

HAZE = {"start": "2015-09-01T00:00", "end": "2015-11-01T00:00"}
PEAK = {**HAZE, "kind": "peak_region", "region": "west", "statement": "West peaked."}


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


class Replies:
    def __init__(self, *replies: str):
        self._replies = list(replies)

    def complete(self, prompt: str, max_tokens: int) -> str:
        return self._replies.pop(0) if self._replies else "safe"


def guard(*replies: str) -> LlamaGuard:
    return LlamaGuard(Replies(*replies), "llama-guard-test")


def test_text_that_fails_twice_is_replaced_by_a_rendered_answer(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            call("submit_findings", claims=[PEAK]),
            say("West peaked on 19 October at 471 (R1.1)."),
            say("West peaked in October at 471 (R1.1)."),
        ]
    )
    result = investigate(
        "Which region peaked in the 2015 haze?",
        client,
        workspace,
        tmp_path,
        options=RENDER,
    )
    assert result.status is RunStatus.VERIFIED
    assert result.answer_source == "rendered" and result.answer_issues == ()
    assert result.answer.startswith("Verified findings")
    assert "R1.1" in result.answer and "west" in result.answer
    assert "19 October" not in result.answer  # no model sentence is copied
    saved = json.loads((tmp_path / "result.json").read_text())
    assert saved["answer_source"] == "rendered"
    records = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    withheld = next(r for r in records if r["event"] == "answer_rendered")
    assert "471" in withheld["data"]["withheld_text"]
    summaries = [e.message_summary for e in load_run(tmp_path).events]
    assert any("rendered from verified findings" in s for s in summaries)
    assert not any("19 October" in s for s in summaries)


def test_without_the_fallback_a_failed_text_stays_unverified(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            call("submit_findings", claims=[PEAK]),
            say("West peaked at 471 (R1.1)."),
            say("West peaked at 471 (R1.1)."),
        ]
    )
    result = investigate("Which region peaked?", client, workspace, tmp_path)
    assert result.status is RunStatus.ANSWER_UNVERIFIED and result.answer_source == "model"


def test_text_that_passes_after_revision_stays_the_model_text(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            call("submit_findings", claims=[PEAK]),
            say("West peaked at 471 (R1.1)."),
            say("West had the highest hourly value (R1.1)."),
        ]
    )
    result = investigate(
        "Which region peaked?",
        client,
        workspace,
        tmp_path,
        options=RENDER,
    )
    assert result.status is RunStatus.VERIFIED and result.answer_source == "model"


def test_nothing_to_render_without_findings_or_limitations() -> None:
    assert render_answer(FindingsLedger(), AreaLedger(), []) is None


def test_s5_only_question_block_becomes_a_causal_abstention(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient([say("never called")])
    question = "Which plantation company caused the haze peak recorded in Singapore?"
    result = investigate(question, client, workspace, tmp_path, guard=guard("unsafe\nS5"))
    assert result.status is RunStatus.ABSTAINED
    assert result.answer == CAUSAL_ABSTENTION
    assert [c.value for e in result.limitations for c in e.reasons] == [
        "causation_not_identifiable"
    ]
    assert client.requests == []  # the planner never ran
    events = load_run(tmp_path).events
    assert any("routed to a typed abstention" in e.message_summary for e in events)
    assert events[-1].event_type == "run_completed" and events[-1].status == "completed"


@pytest.mark.parametrize("reply", ["unsafe\nS5,S3", "unsafe\nS3", "unsafe\nS1", "unsafe"])
def test_every_other_question_block_is_still_a_refusal(
    workspace: Workspace, tmp_path: Path, reply: str
) -> None:
    client = ScriptedClient([say("never called")])
    result = investigate("Some question?", client, workspace, tmp_path, guard=guard(reply))
    assert result.status is RunStatus.REFUSED and client.requests == []


def test_scope_rule_block_and_answer_stage_s5_are_never_rerouted() -> None:
    base: dict[str, Any] = {"allowed": False, "guard_codes": ("S5",)}
    answer = SafetyDecision(stage=Stage.ANSWER, blocked_by="llama_guard", **base)
    rules = SafetyDecision(stage=Stage.QUESTION, blocked_by="scope_rules", **base)
    question = SafetyDecision(stage=Stage.QUESTION, blocked_by="llama_guard", **base)
    assert not answer.causal_only() and not rules.causal_only()
    assert question.causal_only()
