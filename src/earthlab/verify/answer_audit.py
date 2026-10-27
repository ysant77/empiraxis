"""Bind every number in the model's final prose to a supported claim about the same region.

The verifier checks typed claims. The final answer is free text, so this audit checks it
sentence by sentence. A number must equal the value or threshold of a supported claim, and
the region it belongs to (the last one named before it, else the next one) must be that
claim's region. A number seen only in raw tool
output does not count. Numbers quoted from the question count as a hypothesis under test.
Dates, hours, years and unit names are skipped. The text must also pass the scope rules.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from earthlab.contracts import Region, Strict
from earthlab.safety.scope import answer_out_of_scope
from earthlab.verify.claims import Verdict, VerificationResult

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
_REGION = re.compile(r"\b(north|south|east|west|central)(?:ern)?\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+|\n+")

Fact = tuple[Region, float]


class AnswerAudit(Strict):
    numbers_checked: int
    ungrounded: tuple[float, ...] = ()
    misattributed: tuple[str, ...] = ()
    language: str | None = None

    @property
    def passed(self) -> bool:
        return not self.ungrounded and not self.misattributed and self.language is None

    def problems(self) -> list[str]:
        issues = [f"number {n:g} matches no supported claim" for n in self.ungrounded]
        issues += list(self.misattributed)
        if self.language is not None:
            issues.append(self.language)
        return issues


def _mask(text: str) -> str:
    """Blank out dates, times and units, keeping every other character in place."""
    for pattern in _IGNORED:
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _numbers(text: str) -> list[tuple[int, float]]:
    return [(m.start(), float(m.group(0).replace(",", ""))) for m in _NUMBER.finditer(_mask(text))]


def answer_numbers(text: str) -> list[float]:
    return [value for _, value in _numbers(text)]


def claim_facts(results: Iterable[VerificationResult]) -> list[Fact]:
    """(region, number) pairs that supported claims establish: values and thresholds."""
    facts: list[Fact] = []
    for r in results:
        if r.verdict is not Verdict.SUPPORTED:
            continue
        facts += [(r.claim.region, n) for n in (r.claim.value, r.claim.threshold) if n is not None]
    return facts


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= ROUNDING_TOLERANCE


def _subject(regions: list[tuple[int, Region]], pos: int) -> Region:
    """The region a number belongs to: the last one named before it, else the next one."""
    before = [region for start, region in regions if start < pos]
    if before:
        return before[-1]
    return min(regions, key=lambda item: item[0] - pos)[1]


def _check_sentence(
    sentence: str, facts: list[Fact], quoted: list[float]
) -> tuple[list[float], list[str], int]:
    regions = [(m.start(), Region(m.group(1).lower())) for m in _REGION.finditer(sentence)]
    ungrounded: list[float] = []
    misattributed: list[str] = []
    numbers = _numbers(sentence)
    for pos, number in numbers:
        owners = {region for region, value in facts if _close(value, number)}
        if not owners:
            if not any(_close(number, q) for q in quoted):
                ungrounded.append(number)
            continue
        if not regions:
            continue
        nearest = _subject(regions, pos)
        if nearest not in owners:
            names = ", ".join(sorted(r.value for r in owners))
            misattributed.append(f"{number:g} is next to {nearest.value}; supported for {names}")
    return ungrounded, misattributed, len(numbers)


def audit_answer(
    answer: str, supported: Iterable[VerificationResult], question: str = ""
) -> AnswerAudit:
    facts = claim_facts(supported)
    quoted = answer_numbers(question)
    ungrounded: list[float] = []
    misattributed: list[str] = []
    checked = 0
    for sentence in _SENTENCE_END.split(answer):
        bad, wrong, count = _check_sentence(sentence, facts, quoted)
        ungrounded += bad
        misattributed += wrong
        checked += count
    return AnswerAudit(
        numbers_checked=checked,
        ungrounded=tuple(ungrounded),
        misattributed=tuple(misattributed),
        language=answer_out_of_scope(answer),
    )
