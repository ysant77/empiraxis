"""Contract rules for the method review: registered names, training budget, fixed criteria.

Model text may name a method in its own words. Only a registered name, or an alias listed here,
maps to a method. A name that could mean more than one method maps to none. A review may not
move the success measure, test on the sealed period, or bring a threshold that no measured
record or registered criterion holds. Code applies these rules; no model text can relax them.
"""

from __future__ import annotations

import re
from typing import Any

from earthlab.forecast.dataset import SPLITS
from earthlab.harness.contracts import MethodProposalV1, ProblemSpecV1

ALIASES = {
    "persistence alarm": "persistence", "persistence baseline": "persistence",
    "climatology baseline": "climatology", "ridge regression": "ridge", "lagged ridge": "ridge",
    "logistic regression": "logistic", "tree classifier": "trees_classifier",
    "gated recurrent unit": "gru", "temporal convolutional network": "tcn",
    "raster deterministic": "raster_deterministic",
}  # fmt: skip
AMBIGUOUS = frozenset({
    "tree ensemble", "random forest", "gradient boosting", "neural network", "deep learning",
    "rnn", "lstm", "linear model", "regression", "baseline", "machine learning",
})  # fmt: skip
SEALED_YEAR = SPLITS["test"][0].year
_SEALED = re.compile(r"\b(?:test (?:split|period|set|years?)|held[- ]?out|holdout|sealed)\b", re.I)
_YEAR = re.compile(r"\b(20\d\d)\b")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _key(name: str) -> str:
    return re.sub(r"[\s_-]+", " ", name.strip().lower())


def registered_name(name: str, registry: dict[str, str]) -> str | None:
    """The registered method a name means, or None when it is unknown or ambiguous."""
    if name in registry:
        return name
    key = _key(name)
    if key in AMBIGUOUS:
        return None
    if key.replace(" ", "_") in registry:
        return key.replace(" ", "_")
    method = ALIASES.get(key)
    return method if method in registry else None


def is_ambiguous(name: str) -> bool:
    return _key(name) in AMBIGUOUS


def normalize(
    proposal: MethodProposalV1, registry: dict[str, str]
) -> tuple[MethodProposalV1, list[str]]:
    """Map each listed alias to its registered name. Unknown names stay for code to refuse."""
    notes: list[str] = []

    def mapped(name: str) -> str:
        method = registered_name(name, registry)
        if method is None or method == name:
            return name
        notes.append(f"{name} -> {method}")
        return method

    data = proposal.model_dump(mode="json")
    data["proposed_method"] = mapped(proposal.proposed_method)
    data["simplest_baseline"] = mapped(proposal.simplest_baseline)
    data["candidates"] = [{**c, "method": mapped(c["method"])} for c in data["candidates"]]
    return MethodProposalV1.model_validate(data), list(dict.fromkeys(notes))


def sealed_issues(text: str) -> list[str]:
    """A critique may not test on the sealed period. Only validation years are open."""
    years = [int(y) for y in _YEAR.findall(text)]
    if _SEALED.search(text) or any(year >= SEALED_YEAR for year in years):
        return [f"test.samples: the period from {SEALED_YEAR}-01-01 is sealed; use validation"]
    return []


def _numbers(value: Any) -> set[float]:
    return {float(n) for n in _NUMBER.findall(str(value))}


def allowed_thresholds(
    problem: ProblemSpecV1, profile: Any, proposal: MethodProposalV1, metric: str
) -> set[float]:
    """Zero, measured profile values, registered criteria and the case's own stated limits."""
    allowed = {0.0} | _numbers(profile.model_dump(mode="json")) | _numbers(problem.threshold)
    allowed |= _numbers(problem.success_criteria) | _numbers(proposal.failure_conditions)
    if metric == proposal.expected_benefit.metric:
        allowed.add(proposal.expected_benefit.minimum_gain)
    return allowed


def threshold_issues(threshold: float, allowed: set[float]) -> list[str]:
    if any(abs(threshold - value) < 1e-9 for value in allowed):
        return []
    return [f"test.threshold: {threshold:g} is not a measured value or a registered criterion"]


def drift_issues(revised: MethodProposalV1, original: MethodProposalV1) -> list[str]:
    """An answer may add a method or a risk. It may not move the measure of success."""
    issues = []
    if revised.expected_benefit != original.expected_benefit:
        issues.append("revised_case: expected_benefit is fixed; a review cannot change it")
    dropped = [c for c in original.failure_conditions if c not in revised.failure_conditions]
    issues += [f"revised_case: failure condition removed or changed: {c}" for c in dropped]
    return issues


def trains(method: str, registry: dict[str, str]) -> bool:
    """A deterministic method fits nothing, so the training budget does not apply to it."""
    return registry.get(method) != "deterministic"
