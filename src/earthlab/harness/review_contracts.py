"""Contract rules for the method review: registered names, training budget, fixed criteria.

Model text may name a method in its own words. Only a registered name, or an alias listed here
for the task kind, maps to a method. A name that could mean more than one method maps to none,
and a name that carries a feature setting (a lag window) is refused, not cut down. A review may
not move the success measure, test on the sealed period of the registered split, or bring a
threshold that no typed criterion for that metric holds. Code applies these rules; no model text
can relax them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from earthlab.forecast.dataset import SPLITS
from earthlab.harness.contracts import MethodProposalV1, ProblemSpecV1

REGRESSION, CLASSIFICATION, RASTER = "regression", "classification", "raster_method"
# An alias holds only for the task kinds where the registered method has the same output.
ALIASES: dict[str, tuple[str, frozenset[str]]] = {
    "persistence alarm": ("persistence", frozenset({CLASSIFICATION})),
    "persistence baseline": ("persistence", frozenset({REGRESSION, CLASSIFICATION})),
    "climatology baseline": ("climatology", frozenset({REGRESSION, CLASSIFICATION})),
    "ridge regression": ("ridge", frozenset({REGRESSION})),
    "lagged ridge": ("ridge", frozenset({REGRESSION})),
    "logistic regression": ("logistic", frozenset({CLASSIFICATION})),
    "tree classifier": ("trees_classifier", frozenset({CLASSIFICATION})),
    "gated recurrent unit": ("gru", frozenset({REGRESSION})),
    "temporal convolutional network": ("tcn", frozenset({REGRESSION})),
    "raster deterministic": ("raster_deterministic", frozenset({RASTER})),
}
AMBIGUOUS = frozenset({
    "tree ensemble", "random forest", "gradient boosting", "neural network", "deep learning",
    "rnn", "lstm", "linear model", "regression", "baseline", "machine learning",
})  # fmt: skip
_SETTING = re.compile(r"\b\d+\s*(?:h|hr|hours?|d|days?)\b|\blags?\b|\bwindow\b", re.I)
_SEALED = re.compile(r"\b(?:test (?:split|period|set|years?)|held[- ]?out|holdout|sealed)\b", re.I)
_TEST_WORD = re.compile(r"\btest(?:ing)?\b", re.I)
_YEAR = re.compile(r"\b(20\d\d)\b")
# The sealed span of each registered experiment. None: the experiment has no time split.
SEALED_SPANS: dict[str, tuple[datetime, datetime] | None] = {
    "pm25-regression-6h": SPLITS["test"],
    "pm25-exceedance-6h": SPLITS["test"],
    "pm25-regression-families-6h": SPLITS["test"],
    "pm25-method-comparison-6h": SPLITS["test"],
    "burned-area-method": None,
}
SKILL_METRICS = frozenset({"skill", "skill_against_persistence"})


@dataclass(frozen=True)
class Criterion:
    """A threshold a critique may test against, with where it comes from."""

    metric: str
    unit: str
    split: str
    source: str
    threshold: float

    def text(self) -> str:
        return f"{self.metric} {self.threshold:g} {self.unit} on {self.split} ({self.source})"


def _key(name: str) -> str:
    return re.sub(r"[\s_-]+", " ", name.strip().lower())


def registered_name(name: str, registry: dict[str, str], kind: str | None = None) -> str | None:
    """The registered method a name means for this task kind, or None."""
    if name in registry:
        return name
    key = _key(name)
    if key in AMBIGUOUS:
        return None
    if key.replace(" ", "_") in registry:
        return key.replace(" ", "_")
    method, kinds = ALIASES.get(key, (None, frozenset()))
    if method not in registry or (kind is not None and kind not in kinds):
        return None
    return method


def unknown_reason(name: str) -> str:
    """Why code refuses a name, in words the Lead can act on."""
    if _key(name) in AMBIGUOUS:
        return "ambiguous: name one method"
    setting = _SETTING.search(name)
    if setting:
        return (
            f"names a feature setting ({setting.group(0)}): name the method alone; "
            "the lag window is the plan's typed config, not part of the name"
        )
    return "not a registered method"


def normalize(
    proposal: MethodProposalV1, registry: dict[str, str], kind: str
) -> tuple[MethodProposalV1, list[str]]:
    """Map each alias for this task kind to its registered name. Others stay for refusal."""
    notes: list[str] = []

    def mapped(name: str) -> str:
        method = registered_name(name, registry, kind)
        if method is None or method == name:
            return name
        notes.append(f"{name} -> {method}")
        return method

    data = proposal.model_dump(mode="json")
    data["proposed_method"] = mapped(proposal.proposed_method)
    data["simplest_baseline"] = mapped(proposal.simplest_baseline)
    data["candidates"] = [{**c, "method": mapped(c["method"])} for c in data["candidates"]]
    return MethodProposalV1.model_validate(data), list(dict.fromkeys(notes))


def sealed_issues(text: str, problem_id: str, samples: str = "") -> list[str]:
    """A critique may not test on the sealed span of the registered split.

    In the samples field, the word "test" alone names the sealed split ("test forecasts").
    """
    if _SEALED.search(text) or _TEST_WORD.search(samples):
        return ["test.samples: the test period is sealed; use validation"]
    text = f"{samples} {text}"
    years = [int(y) for y in _YEAR.findall(text)]
    if problem_id not in SEALED_SPANS:
        return [f"test.samples: no split is registered for {problem_id}; name no year"] * bool(
            years
        )
    span = SEALED_SPANS[problem_id]
    if span is not None and any(year >= span[0].year for year in years):
        return [f"test.samples: the period from {span[0]:%Y-%m-%d} is sealed; use validation"]
    return []


def _unit(metric: str, problem: ProblemSpecV1) -> str:
    return problem.unit if "mae" in metric else "1"


def criteria(problem: ProblemSpecV1, proposal: MethodProposalV1) -> list[Criterion]:
    """Typed thresholds only. Profile counts, years, event limits and prose are not criteria."""
    gain = proposal.expected_benefit
    found = [
        Criterion(
            gain.metric, _unit(gain.metric, problem), "validation",
            "proposal.expected_benefit.minimum_gain", gain.minimum_gain,
        ),
    ]  # fmt: skip
    found += [
        Criterion(m, "1", "validation", "evaluator: skill 0 equals the baseline", 0.0)
        for m in sorted(SKILL_METRICS)
    ]
    return found


def threshold_issues(
    metric: str, threshold: float, problem: ProblemSpecV1, proposal: MethodProposalV1
) -> list[str]:
    """The threshold must equal a typed criterion for the same metric and unit."""
    known = [c for c in criteria(problem, proposal) if c.metric == metric]
    if any(abs(threshold - c.threshold) < 1e-9 for c in known):
        return []
    have = "; ".join(c.text() for c in known) or "none"
    return [f"test.threshold: {threshold:g} is not a criterion for {metric}; registered: {have}"]


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
