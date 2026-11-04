"""An advisory critic of the model-selection decision, run by a model that code does not trust.

After the evaluator scores the models and the Lead recommends, a critic reads the evaluator's
numbers and the recommendation. It may raise up to three findings. Each finding must cite
evaluator numbers, and code checks every cited value against the report. The critic cannot
change a score, an outcome, a claim or an approval. A finding that code refuses is recorded as
refused. If the critic fails, the run goes on and the record says so.
"""

from __future__ import annotations

import re
from typing import Any, Literal, get_args

from pydantic import Field, model_validator

from earthlab.agent.budget import BudgetStop
from earthlab.contracts import Strict
from earthlab.forecast.gate import unbacked_numbers
from earthlab.harness.contracts import DecisionRecordV1, EvaluationReportV1
from earthlab.harness.review_contracts import sealed_issues
from earthlab.harness.seats import Seats, Stopped
from earthlab.llm.types import ProviderError

CRITIC, LEAD = "method_critic", "geospatial_engineer"
TOLERANCE = 0.005
FindingKind = Literal[
    "selection_not_supported", "subgroup_worse", "interval_overlap", "cost_not_justified",
    "validation_reuse", "other_measurable",
]  # fmt: skip
SYSTEM = "You are an independent scientific critic. You read the evaluator's numbers and one \
recommendation. Call submit_critique. Raise a finding only when the numbers show a problem with \
the recommendation. Each finding cites evaluator fields with their exact values, and names one \
measurement that would prove the finding wrong. If the recommendation fits the numbers, use \
verdict no_concern and give no finding. You cannot change a score, an outcome or an approval. \
Do not name a cause of haze. Do not give health advice."
_PRAISE = re.compile(
    r"\b(?:looks? (?:good|fine)|well[- ]chosen|i agree|excellent|great|solid|sound decision)\b",
    re.IGNORECASE,
)
_CAUSE = re.compile(r"\b(?:caused by|because of (?:the )?fires?|health advice|safe to)\b", re.I)


class Evidence(Strict):
    field: str = Field(min_length=3, max_length=80)
    value: float


class CriticFinding(Strict):
    kind: FindingKind
    claim: str = Field(min_length=20, max_length=300)
    evidence: tuple[Evidence, ...] = Field(min_length=1, max_length=3)
    falsified_by: str = Field(min_length=10, max_length=200)


class DecisionCritiqueV1(Strict):
    schema_version: Literal["1"] = "1"
    verdict: Literal["no_concern", "concerns"]
    findings: tuple[CriticFinding, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def _verdict_matches_findings(self) -> DecisionCritiqueV1:
        if (self.verdict == "concerns") != bool(self.findings):
            raise ValueError("verdict concerns needs at least one finding; no_concern needs none")
        return self


def fact_table(report: EvaluationReportV1) -> dict[str, float]:
    """Every number a finding may cite, named model.metric or model.subgroup.metric."""
    facts: dict[str, float] = {}
    for score in report.scores:
        for name, value in score.metrics.items():
            if value is not None:
                facts[f"{score.model}.{name}"] = float(value)
        for edge, value in (("low", score.low), ("high", score.high)):
            if value is not None:
                facts[f"{score.model}.skill_{edge}"] = float(value)
        for group, metrics in score.subgroups.items():
            facts |= {f"{score.model}.{group}.{k}": float(v) for k, v in metrics.items() if v}
    return facts


def evidence_issues(finding: CriticFinding, facts: dict[str, float]) -> list[str]:
    issues = []
    for item in finding.evidence:
        known = facts.get(item.field)
        if known is None:
            issues.append(f"evidence.field {item.field} is not an evaluator field")
        elif abs(item.value - known) > max(0.0005, TOLERANCE * abs(known)):
            issues.append(f"evidence {item.field}={item.value:g} differs from {known:g}")
    return issues


def finding_issues(
    finding: CriticFinding, facts: dict[str, float], problem_id: str
) -> list[str]:  # fmt: skip
    text = f"{finding.claim} {finding.falsified_by}"
    issues = evidence_issues(finding, facts)
    issues += unbacked_numbers(text, dict(facts))
    issues += sealed_issues(text, problem_id)
    if _PRAISE.search(text):
        issues.append("praise is not a finding")
    if _CAUSE.search(text):
        issues.append("a finding may not name a cause or give advice")
    return issues


def critique_issues(
    critique: DecisionCritiqueV1, facts: dict[str, float], problem_id: str
) -> list[str]:  # fmt: skip
    return [i for f in critique.findings for i in finding_issues(f, facts, problem_id)]


def judged(
    critique: DecisionCritiqueV1, facts: dict[str, float], problem_id: str
) -> list[dict[str, Any]]:
    """Each finding with the code's verdict on it."""
    out = []
    for f in critique.findings:
        issues = finding_issues(f, facts, problem_id)
        out.append(f.model_dump(mode="json") | {"backed": not issues, "issues": issues})
    return out


def _sent(report: EvaluationReportV1, decision: DecisionRecordV1) -> dict[str, Any]:
    keep = ("outcome", "selected", "reason", "limitations")
    return {
        "recommendation": {k: getattr(decision, k) for k in keep},
        "reference": report.reference, "split_scored": report.split_scored,
        "evaluator_fields": fact_table(report), "evaluator_failures": list(report.failures),
        "kinds": list(get_args(FindingKind)),
    }  # fmt: skip


def run_critic(
    seats: Seats, report: EvaluationReportV1, decision: DecisionRecordV1, problem_id: str,
    source: str,
) -> dict[str, Any]:  # fmt: skip
    """One critic call and one correction. Returns the record that goes in the trace and result."""
    facts = fact_table(report)
    base: dict[str, Any] = {"critic_source": source, "advisory": True}
    try:
        critique = seats.propose(
            CRITIC, SYSTEM, _sent(report, decision), "submit_critique", DecisionCritiqueV1,
            lambda value: critique_issues(value, facts, problem_id),
        )  # fmt: skip
    except (Stopped, BudgetStop, ProviderError) as exc:
        state = "unusable" if isinstance(exc, Stopped) else "unavailable"
        record = base | {"state": state, "reason": str(exc)[:200], "verdict": None, "findings": []}
    else:
        record = base | {
            "state": "usable", "verdict": critique.verdict, "reason": "",
            "findings": judged(critique, facts, problem_id),
        }  # fmt: skip
    seats.trace.append("decision_critique", "runtime", **record)
    return record
