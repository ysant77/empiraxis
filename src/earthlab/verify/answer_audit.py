"""Check the model's interpretation text against the supported claims.

Numbers, units, windows and times live only in the Findings table, which is rendered from
supported claims. The interpretation text may refer to a finding by its ID (R1.2) but may
not contain any digit, date or month name. Its remaining factual words are checked too:
"highest" needs a supported peak_region claim for that region, and "higher than" needs two
supported claims of the same kind and window, in the stated order. The text must also pass
the answer scope rules.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from earthlab.contracts import Region, Strict
from earthlab.safety.scope import answer_out_of_scope
from earthlab.verify.claims import ClaimKind, Verdict, VerificationResult

_CITATION = re.compile(r"\bR\d+\.\d+\b")
_NAMES = re.compile(r"\bPM\s?2[._]?5\b|[µu]g\s*/\s*m(?:3|³)", re.IGNORECASE)
_DIGITS = re.compile(r"\d+(?:[.,:/-]\d+)*")
_NUMBER_WORDS = re.compile(
    r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundreds?|thousands?|"
    r"millions?|billions?|dozens?)\b",
    re.IGNORECASE,
)
_MONTH = re.compile(
    r"\b(january|february|march|april|june|july|august|september|october|november|"
    r"december|jan|feb|apr|jun|jul|aug|sept?|oct|nov|dec)\b",
    re.IGNORECASE,
)
_REGION = re.compile(r"\b(north|south|east|west|central)(?:ern)?\b", re.IGNORECASE)
_TOP = re.compile(r"\b(highest|greatest|worst|most polluted)\b", re.IGNORECASE)
_BOTTOM = re.compile(r"\b(lowest|cleanest)\b", re.IGNORECASE)
_MORE = re.compile(r"\b(higher|greater|more|larger|worse)\s+than\b", re.IGNORECASE)
_LESS = re.compile(r"\b(lower|less|smaller|better)\s+than\b", re.IGNORECASE)
_MEAN = re.compile(r"\b(mean|average)\b", re.IGNORECASE)
_NOT = re.compile(r"\b(not|no|never|neither|nor|isn't|wasn't|unsupported|contradicted)\b", re.I)
_HYPOTHESIS = re.compile(
    r"\b(claim\w*|hypothes\w*|colleague\w*|question|suggest\w*|said|says)\b", re.I
)
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+|\n+")
_COMPARABLE = (ClaimKind.REGION_MAX, ClaimKind.REGION_MEAN)


class AnswerAudit(Strict):
    numbers: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    unknown_citations: tuple[str, ...] = ()
    misleading: tuple[str, ...] = ()
    language: str | None = None

    @property
    def passed(self) -> bool:
        return not self.problems()

    def problems(self) -> list[str]:
        issues: list[str] = []
        if self.numbers:
            issues.append(f"numbers in the text ({', '.join(self.numbers)}); use the Findings")
        if self.dates:
            issues.append(f"dates in the text ({', '.join(self.dates)}); use the Findings")
        issues += [f"{c} is not a supported finding" for c in self.unknown_citations]
        issues += list(self.misleading)
        if self.language is not None:
            issues.append(self.language)
        return issues


def text_numbers(text: str) -> list[str]:
    """Digit runs and large number words, after removing finding IDs, PM2.5 and ug/m3.

    Small number words (one, two) are common in plain text and are not counted.
    """
    plain = _NAMES.sub(" ", _CITATION.sub(" ", text))
    return _DIGITS.findall(plain) + [m.group(0) for m in _NUMBER_WORDS.finditer(plain)]


def _regions(sentence: str) -> list[tuple[int, Region]]:
    return [(m.start(), Region(m.group(1).lower())) for m in _REGION.finditer(sentence)]


def _subject(regions: list[tuple[int, Region]], pos: int) -> Region | None:
    """The region a phrase is about: the last one named before it, else the next one."""
    before = [region for start, region in regions if start < pos]
    if before:
        return before[-1]
    after = [region for start, region in regions if start > pos]
    return after[0] if after else None


def _denied(sentence: str, regions: list[tuple[int, Region]], pos: int) -> bool:
    """True for 'central is not the worst' and 'the claim that central was highest is not
    supported'. A negation after the phrase alone ('highest, not west') does not count."""
    if _HYPOTHESIS.search(sentence) and _NOT.search(sentence):
        return True
    start = max((p for p, _ in regions if p < pos), default=0)
    return bool(_NOT.search(sentence[start:pos]))


def _superlatives(sentence: str, supported: list[VerificationResult]) -> list[str]:
    regions = _regions(sentence)
    issues: list[str] = []
    for m in _TOP.finditer(sentence):
        region = _subject(regions, m.start())
        tops = {r.claim.region for r in supported if r.claim.kind is ClaimKind.PEAK_REGION}
        if region is not None and region not in tops and not _denied(sentence, regions, m.start()):
            issues.append(f"'{m.group(0)}' for {region.value} has no supported peak_region claim")
    for m in _BOTTOM.finditer(sentence):
        if _subject(regions, m.start()) is not None:
            issues.append(f"'{m.group(0)}' has no supported claim kind")
    return issues


def _values(
    region: Region, supported: list[VerificationResult], kinds: tuple[ClaimKind, ...]
) -> dict[tuple[ClaimKind, str], float]:
    return {
        (r.claim.kind, r.claim.window.model_dump_json()): r.claim.value
        for r in supported
        if r.claim.region is region and r.claim.kind in kinds and r.claim.value is not None
    }


def _comparison(sentence: str, supported: list[VerificationResult]) -> list[str]:
    match = _MORE.search(sentence) or _LESS.search(sentence)
    if match is None:
        return []
    regions = _regions(sentence)
    left = _subject([(p, r) for p, r in regions if p < match.start()], match.start())
    right = next((r for p, r in regions if p > match.start()), None)
    if left is None or right is None:
        return []
    more = match.re is _MORE
    top, low = (left, right) if more else (right, left)
    peaks = {r.claim.region for r in supported if r.claim.kind is ClaimKind.PEAK_REGION}
    what = f"comparison of {left.value} and {right.value}"
    if not _MEAN.search(sentence) and (top in peaks or low in peaks):
        return [] if top in peaks else [f"{what} contradicts the supported claims"]
    kinds = (ClaimKind.REGION_MEAN,) if _MEAN.search(sentence) else _COMPARABLE
    a, b = _values(left, supported, kinds), _values(right, supported, kinds)
    pairs = [(a[key], b[key]) for key in a.keys() & b.keys()]
    if not pairs:
        return [f"{what} has no pair of supported claims with the same kind and window"]
    if all((x > y) if more else (x < y) for x, y in pairs):
        return []
    return [f"{what} contradicts the supported claims"]


def audit_answer(answer: str, findings: Mapping[str, VerificationResult]) -> AnswerAudit:
    """Audit the text against the latest submission, keyed by finding ID (R<round>.<n>)."""
    supported = [r for r in findings.values() if r.verdict is Verdict.SUPPORTED]
    cited = _CITATION.findall(answer)
    unknown = [
        c for c in cited if c not in findings or findings[c].verdict is not Verdict.SUPPORTED
    ]
    misleading: list[str] = []
    for sentence in _SENTENCE_END.split(answer):
        misleading += _superlatives(sentence, supported) + _comparison(sentence, supported)
    return AnswerAudit(
        numbers=tuple(text_numbers(answer)),
        dates=tuple(m.group(0) for m in _MONTH.finditer(answer)),
        unknown_citations=tuple(dict.fromkeys(unknown)),
        misleading=tuple(misleading),
        language=answer_out_of_scope(answer),
    )
