"""Small helpers shared by the model roles: chat messages and final-text issues."""

from __future__ import annotations

from typing import Any

from earthlab.llm.types import ChatResponse
from earthlab.safety.gate import SafetyDecision
from earthlab.verify.answer_audit import AnswerAudit


def assistant_message(resp: ChatResponse) -> dict[str, Any]:
    """The reply as the assistant message that goes back into the conversation."""
    message: dict[str, Any] = {"role": "assistant", "content": resp.content}
    if resp.tool_calls:
        message["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in resp.tool_calls
        ]
    return message


def answer_issues(
    audit: AnswerAudit | None,
    decision: SafetyDecision | None,
    rendered: bool,
    revision_note: str | None,
) -> tuple[str, ...]:
    """Why the final text cannot be called verified; empty when it can."""
    issues = [] if audit is None or rendered else audit.problems()
    if revision_note is not None and issues:
        issues.append(revision_note)
    if decision is not None and not decision.allowed:
        issues.append(f"safety check withheld the text: {decision.reason}")
    return tuple(issues)
