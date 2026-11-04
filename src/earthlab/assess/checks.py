"""Deterministic checks of role outputs against the evidence package.

The checks validate facts, not opinions: references exist, cited values match, numbers in
text come from the package, decisions are allowed, inputs are available at issue time, and
the text makes no causal, operational or sealed-period claim. A model cannot change them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from earthlab.assess import policy
from earthlab.assess.contracts import (
    Availability,
    CheckReportV1,
    CheckV1,
    Decision,
    EvidencePackageV1,
    FindingV1,
)

TOLERANCE = 0.005
PROCEEDS = {Decision.ADOPT, Decision.ADOPT_LIMITED, Decision.PROCEED_WITH_LIMITS}
INPUT_ROLES = {"observation", "estimate", "reanalysis"}
FORBIDDEN = {
    "causal": re.compile(
        r"\b(caused by|causes? the|due to (the )?fires?|attributable to|responsible for the)\b",
        re.I,
    ),
    "operational": re.compile(
        r"\b(operational forecast|will forecast|forecasts? tomorrow)\b", re.I
    ),
    "sealed": re.compile(r"\btest[- ](period|set) (mae|scores?|skill|results?)\b", re.I),
    "certainty": re.compile(r"\b(proves?|guarantees?|definitively)\b", re.I),
}
_DECIMAL = re.compile(r"(?<![\w.])-?\d+\.\d+(?![\w.])")


def ids_of(pkg: EvidencePackageV1) -> set[str]:
    return {f.id for f in pkg.facts} | {s.id for s in pkg.sources}


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOLERANCE * abs(b), 0.001)


def grounded_number(text: str, values: Iterable[float]) -> bool:
    """A decimal in text is grounded when some package value rounds to it."""
    number = float(text)
    places = len(text.split(".")[1])
    return any(round(v, places) == number or _close(number, v) for v in values)


def ungrounded_numbers(texts: Iterable[str], pkg: EvidencePackageV1) -> list[str]:
    values = [f.value for f in pkg.facts if f.value is not None]
    found = [m for t in texts for m in _DECIMAL.findall(t)]
    return [n for n in found if not grounded_number(n, values)]


def forbidden_phrases(texts: Iterable[str]) -> list[str]:
    hits: list[str] = []
    for text in texts:
        hits += [name for name, rx in FORBIDDEN.items() if rx.search(text)]
    return sorted(set(hits))


def finding_problems(f: FindingV1, pkg: EvidencePackageV1) -> list[str]:
    """Empty when the finding is backed by the package."""
    known, facts = ids_of(pkg), {x.id: x for x in pkg.facts}
    out = [f"unknown ref {r}" for r in f.evidence if r not in known]
    for ref, value in f.cited_values.items():
        if ref not in facts or facts[ref].value is None:
            out.append(f"cited {ref} is not a numeric fact")
        elif not _close(value, float(facts[ref].value)):  # type: ignore[arg-type]
            out.append(f"cited {ref}={value} but the package has {facts[ref].value}")
    out += [f"number {n} not in package" for n in ungrounded_numbers([f.claim], pkg)]
    out += [f"forbidden {w}" for w in forbidden_phrases([f.claim])]
    return out


def findings_report(subject: str, items: list[FindingV1], pkg: EvidencePackageV1) -> CheckReportV1:
    checks = []
    for f in items:
        problems = finding_problems(f, pkg)
        checks.append(
            CheckV1(name=f"finding {f.id}", passed=not problems, detail="; ".join(problems))
        )
    return CheckReportV1(subject=subject, checks=checks)


def unavailable_inputs(inputs: Iterable[str], pkg: EvidencePackageV1) -> list[str]:
    """Inputs that are not known to be available at issue time, or that the code rule
    excludes because an essential quality measurement is missing (design scenario)."""
    by_id = {s.id: s for s in pkg.sources}
    unmeasured = set(policy.decide(pkg).excluded_inputs) if pkg.scenario == "design" else set()
    return [
        i
        for i in inputs
        if i in by_id
        and by_id[i].role in INPUT_ROLES
        and (by_id[i].availability is not Availability.ISSUE_TIME_VALID or i in unmeasured)
    ]


def plan_report(
    subject: str,
    pkg: EvidencePackageV1,
    *,
    decision: Decision,
    inputs_used: list[str],
    excluded: list[str],
    texts: list[str],
) -> CheckReportV1:
    """Checks on a Lead plan or a revised plan."""
    sources = {s.id for s in pkg.sources}
    unknown = [i for i in inputs_used + excluded if i not in sources]
    forecasting = pkg.scenario in ("sufficiency", "design")
    late = unavailable_inputs(inputs_used, pkg) if forecasting and decision in PROCEEDS else []
    numbers = ungrounded_numbers(texts, pkg)
    words = forbidden_phrases(texts)
    checks = [
        CheckV1(
            name="decision_allowed", passed=decision in pkg.allowed_decisions, detail=decision.value
        ),
        CheckV1(name="inputs_known", passed=not unknown, detail=", ".join(unknown)),
        CheckV1(name="issue_time_inputs", passed=not late, detail=", ".join(late)),
        CheckV1(name="numbers_grounded", passed=not numbers, detail=", ".join(numbers)),
        CheckV1(name="no_forbidden_claims", passed=not words, detail=", ".join(words)),
    ]
    return CheckReportV1(subject=subject, checks=checks)


def coverage_check(name: str, required: Iterable[str], answered: Iterable[str]) -> CheckV1:
    """Every required id has an answer, and no answer names an unknown id."""
    req, ans = set(required), set(answered)
    missing, extra = sorted(req - ans), sorted(ans - req)
    detail = "; ".join(
        x
        for x in (f"missing {missing}" if missing else "", f"unknown {extra}" if extra else "")
        if x
    )
    return CheckV1(name=name, passed=not missing and not extra, detail=detail)
