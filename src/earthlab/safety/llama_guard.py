"""Meta Llama Guard 3 with an EarthLab-specific policy, for the question and final answer.

Llama Guard accepts custom hazard categories in its prompt. The EarthLab policy covers
what this project must never do (health advice, safety recommendations, politics,
forecasts, causal attribution) plus two general hazards. The prompt is sent raw, so the
server's default template cannot replace the policy.
"""

from __future__ import annotations

import re
from typing import Protocol

from earthlab.contracts import Strict

POLICY: tuple[tuple[str, str, str], ...] = (
    (
        "S1",
        "Health or Medical Advice",
        "Content that gives or requests advice about health, "
        "medicine, symptoms, or what a person with a condition should do.",
    ),
    (
        "S2",
        "Safety Recommendations",
        "Content that gives or requests recommendations on "
        "staying indoors, going outside, exercising, wearing masks, or other protective actions.",
    ),
    (
        "S3",
        "Political or Conflict Content",
        "Content about political parties, governments, "
        "elections, blame between countries, retaliation, sanctions, or war.",
    ),
    ("S4", "Forecasts", "Content that predicts future air quality, haze, or fire activity."),
    (
        "S5",
        "Causal Attribution",
        "Content that asserts a specific source or country caused a pollution reading.",
    ),
    ("S6", "Violent Crimes", ""),
    ("S7", "Hate", ""),
)
CATEGORY_NAMES = {code: name for code, name, _ in POLICY}
MAX_GUARD_TOKENS = 12
_VERDICT = re.compile(r"\s*(unsafe|safe)(.*)", re.DOTALL)


class RawCompleter(Protocol):
    def complete(self, prompt: str, max_tokens: int) -> str: ...


class GuardVerdict(Strict):
    safe: bool
    codes: tuple[str, ...] = ()

    def describe(self) -> str:
        if self.safe:
            return "safe"
        names = ", ".join(f"{c} {CATEGORY_NAMES.get(c, 'unknown')}" for c in self.codes)
        return f"unsafe ({names or 'unparsed reply'})"


def _categories() -> str:
    lines: list[str] = []
    for code, name, detail in POLICY:
        lines.append(f"{code}: {name}.")
        if detail:
            lines.append(detail)
    return "\n".join(lines)


def build_prompt(question: str, answer: str | None = None) -> str:
    """Llama Guard 3 prompt; it rates the last User message, or the Agent's answer."""
    role = "User" if answer is None else "Agent"
    conversation = f"User: {question}" + ("" if answer is None else f"\n\nAgent: {answer}")
    return (
        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
        f"Task: Check if there is unsafe content in '{role}' messages in conversations "
        "according our safety policy with the below categories.\n\n"
        f"<BEGIN UNSAFE CONTENT CATEGORIES>\n{_categories()}\n<END UNSAFE CONTENT CATEGORIES>\n\n"
        f"<BEGIN CONVERSATION>\n\n{conversation}\n\n<END CONVERSATION>\n\n"
        f"Provide your safety assessment for ONLY THE LAST {role} message in the above "
        "conversation:\n - First line must read 'safe' or 'unsafe'.\n"
        " - If unsafe, a second line must include a comma-separated list of violated "
        "categories.<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def parse_verdict(reply: str) -> GuardVerdict:
    """Read the first word only; anything else (including empty output) is unsafe."""
    match = _VERDICT.match(reply)
    if match is None:
        return GuardVerdict(safe=False)
    if match.group(1) == "safe":
        return GuardVerdict(safe=True)
    codes = tuple(re.findall(r"S\d+", match.group(2).split("\n\n")[0]))
    return GuardVerdict(safe=False, codes=codes)


class LlamaGuard:
    def __init__(self, completer: RawCompleter, name: str):
        self._completer = completer
        self.name = name

    def classify(self, question: str, answer: str | None = None) -> GuardVerdict:
        reply = self._completer.complete(build_prompt(question, answer), MAX_GUARD_TOKENS)
        return parse_verdict(reply)
