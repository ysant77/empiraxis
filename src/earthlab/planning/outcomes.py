"""Plan-level outcomes: actions the gate refuses, abstentions, and reportable values.

A plan that cannot be answered must say so in typed form. A month outside the data gives
`data_unavailable`; a causal question gives `causation_not_identifiable`. Neither is a
tool error. Only supported, verified findings may carry a value into a report.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from earthlab.cases.models import EvidenceClaim, ObservationStatus
from earthlab.contracts import Strict
from earthlab.planning.plan import AbstentionReason, InvestigationPlan
from earthlab.planning.report import CheckId
from earthlab.planning.rules import Draft
from earthlab.planning.vocab import ActionKind, PlanAction, ResearchIntent


def gate_refusal(action: ActionKind) -> str | None:
    """Why the approval gate refuses this action outright, or None when a human may decide.

    Training and deletion always need approval, and no approval type exists for them yet,
    so the gate refuses both until one is added.
    """
    if isinstance(action, PlanAction):
        return f"{action.value} has no approval type yet; the gate refuses it"
    return None


def refused_actions(plan: InvestigationPlan) -> Iterator[Draft]:
    named = [(f"operations[{i}].action", o.action) for i, o in enumerate(plan.operations)]
    named += [
        (f"approval_requests[{i}].action", r.action) for i, r in enumerate(plan.approval_requests)
    ]
    for path, action in named:
        refusal = gate_refusal(action)
        if refusal is not None:
            yield (
                CheckId.ACTION_NOT_SUPPORTED,
                "error",
                path,
                refusal,
                "remove the step, or wait until the approval type exists",
            )


def causal_abstention(plan: InvestigationPlan) -> Iterator[Draft]:
    causal = ResearchIntent.CAUSAL_INFERENCE
    asked = causal in (plan.requested_intent, plan.research_intent)
    if asked and not plan.abstains("causation_not_identifiable"):
        yield (
            CheckId.CAUSAL_ABSTENTION_MISSING,
            "error",
            "abstentions",
            "a causal question needs a causation_not_identifiable abstention",
            "add the abstention and plan only what the data can support",
        )


def report_abstentions(
    plan: InvestigationPlan, checks: Iterable[CheckId]
) -> tuple[AbstentionReason, ...]:
    """The plan-level answers the run must give, from typed conditions only."""
    reasons: set[AbstentionReason] = set()
    if CheckId.DATA_UNAVAILABLE in set(checks):
        reasons.add("data_unavailable")
    if ResearchIntent.CAUSAL_INFERENCE in (plan.requested_intent, plan.research_intent):
        reasons.add("causation_not_identifiable")
    return tuple(sorted(reasons))


class ReportableValue(Strict):
    claim_id: str
    value: float
    unit: str


def reportable_values(claims: Iterable[EvidenceClaim]) -> tuple[ReportableValue, ...]:
    """Values a report may state: only supported observations that carry a value."""
    return tuple(
        ReportableValue(claim_id=c.claim_id, value=c.value, unit=c.unit)
        for c in claims
        if c.observation_status is ObservationStatus.SUPPORTED_OBSERVATION and c.value is not None
    )
