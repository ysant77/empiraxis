"""The decision rule, on the evaluator's numbers only. No model can change a verdict here."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from earthlab.forecast.contracts import Outcome, Recommendation, Requirements
from earthlab.forecast.samples import HORIZONS, PRIMARY_HORIZON

REFERENCE = "B0_persistence"


def requirement_issues(req: Requirements) -> list[str]:
    """The PM can tighten the rule. It cannot weaken the protocol."""
    issues = []
    if req.primary_horizon_hours != PRIMARY_HORIZON:
        issues.append(f"the primary horizon must be {PRIMARY_HORIZON} h (protocol section 9.1)")
    if set(req.horizons_hours) != set(HORIZONS):
        issues.append(f"the horizons must be {list(HORIZONS)} (protocol section 3)")
    if not req.must_exceed_persistence_lower_limit:
        issues.append("the lower limit must exceed persistence (protocol section 9.1)")
    return issues


@dataclass(frozen=True)
class Verdict:
    model: str
    passed: bool
    reasons: tuple[str, ...]


def verdict(name: str, record: dict[str, Any]) -> Verdict:
    """Section 9.1, applied to validation: this is not the locked test decision."""
    row = record["metrics"][str(PRIMARY_HORIZON)]
    limits = row["limits"]
    reasons = []
    if limits["mean_skill_low"] <= 0:
        reasons.append("the lower limit of mean skill is not above zero")
    if min(limits["region_skill_high"]) < 0:
        reasons.append("a region has a clear loss against persistence")
    return Verdict(name, not reasons, tuple(reasons))


def eligible(results: dict[str, dict[str, Any]]) -> list[str]:
    """Trained candidates and B4 that pass, best validation MAE first."""
    passing = [
        n for n, r in results.items() if n != REFERENCE and n[:2] != "B1" and verdict(n, r).passed
    ]
    passing = [n for n in passing if n[:2] not in ("B2", "B3") and not n.startswith("member")]
    return sorted(passing, key=lambda n: results[n]["metrics"][str(PRIMARY_HORIZON)]["all"]["mae"])


def permitted(rec: Recommendation, results: dict[str, dict[str, Any]]) -> list[str]:
    """Why a recommendation may not stand. Abstention is always allowed."""
    numbers = unbacked_numbers(rec.reason, results)
    if numbers:
        return numbers
    if rec.outcome == "abstain":
        return []
    if rec.outcome == "retain_baseline":
        known = rec.model_id is None or rec.model_id in results
        return [] if known else [f"unknown model {rec.model_id}"]
    if rec.model_id not in results:
        return [f"unknown model {rec.model_id}"]
    if rec.model_id[:1] == "B":
        return ["a baseline is retained, not adopted as a candidate"]
    if rec.model_id not in eligible(results):
        return [f"{rec.model_id} does not pass the rule on validation"]
    return []


def unbacked_numbers(text: str, results: dict[str, Any]) -> list[str]:
    """Decimal values in model text that no evaluator number rounds to."""
    known = [float(value) for value in re.findall(r"-?\d+\.\d+", str(results))]
    wrong = []
    for value in re.findall(r"\d+\.\d+", text):
        places = len(value.split(".")[1])
        if not any(abs(round(abs(k), places) - float(value)) < 1e-9 for k in known):
            wrong.append(f"{value} is not in the evaluator's results")
    return wrong


def default_outcome(results: dict[str, dict[str, Any]]) -> tuple[Outcome, str | None]:
    """What code alone would conclude, for the deterministic arm and for comparison."""
    ranked = eligible(results)
    if not ranked:
        return "retain_baseline", REFERENCE
    best = ranked[0]
    return ("retain_baseline", best) if best[:1] == "B" else ("adopt_candidate", best)
