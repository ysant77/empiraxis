"""Check that every number in the model's final prose came from tool output or a claim.

The verifier checks typed claims. The final answer is free text, so this audit flags any
number in it that no tool returned. Dates, hours, years and unit names are not counted.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from earthlab.contracts import Strict

ROUNDING_TOLERANCE = 0.05 + 1e-9
_MONTHS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_IGNORED = (
    re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:?\d{2}|Z)?)?"),
    re.compile(r"\b\d{1,2}:\d{2}\b"),
    re.compile(r"\bPM\s?2[._]?5\b", re.IGNORECASE),
    re.compile(r"[µu]g\s*/\s*m(?:3|³)", re.IGNORECASE),
    re.compile(r"\b1[- ]?h(?:ou)?r\b", re.IGNORECASE),
    re.compile(rf"\b\d{{1,2}}\s+(?:{_MONTHS})\b", re.IGNORECASE),
    re.compile(rf"\b(?:{_MONTHS})\s+\d{{1,2}}\b", re.IGNORECASE),
    re.compile(r"\b(?:19|20)\d{2}\b"),
)
_NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])\d+(?:\.\d+)?")


class AnswerAudit(Strict):
    numbers_checked: int
    ungrounded: tuple[float, ...]

    @property
    def grounded(self) -> bool:
        return not self.ungrounded


def answer_numbers(text: str) -> list[float]:
    for pattern in _IGNORED:
        text = pattern.sub(" ", text)
    return [float(m.group(0).replace(",", "")) for m in _NUMBER.finditer(text)]


def evidence_numbers(payloads: Iterable[Any]) -> set[float]:
    """Every number inside tool outputs and claim values, at any depth."""
    found: set[float] = set()
    stack = list(payloads)
    while stack:
        item = stack.pop()
        if isinstance(item, bool):
            continue
        if isinstance(item, int | float):
            found.add(float(item))
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list | tuple):
            stack.extend(item)
    return found


def audit_answer(answer: str, payloads: Iterable[Any], question: str = "") -> AnswerAudit:
    """Numbers quoted from the question (a hypothesis to test) count as evidence too."""
    evidence = evidence_numbers(payloads) | set(answer_numbers(question))
    numbers = answer_numbers(answer)
    ungrounded = tuple(
        n for n in numbers if not any(abs(n - e) <= ROUNDING_TOLERANCE for e in evidence)
    )
    return AnswerAudit(numbers_checked=len(numbers), ungrounded=ungrounded)
