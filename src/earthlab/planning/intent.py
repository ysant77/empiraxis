"""What the question asks for, decided by the runtime and not by the model's plan.

The critic reads `requested_intent` from the plan. If the model labels a causal question as
non-causal, the critic cannot require the causal abstention. This module looks for causal
wording in the question itself and corrects the label before the review. The check only
moves a plan toward the causal intent, never away from it: a false match costs a needless
abstention, a missed match lets claims stand where the question asked for a cause.
"""

from __future__ import annotations

import re

from earthlab.planning.plan import InvestigationPlan
from earthlab.planning.vocab import ResearchIntent

CAUSAL_WORDING = re.compile(
    r"\b("
    r"caus(?:e|ed|es|ing|al|ation)"
    r"|responsible\s+for"
    r"|attribut(?:e|ed|es|able|ion)"
    r"|due\s+to|because\s+of"
    r"|lead\s+to|leads\s+to|led\s+to|driven\s+by|drove"
    r"|blamed?|blames"
    r")\b",
    re.IGNORECASE,
)


def asks_for_cause(question: str) -> bool:
    return CAUSAL_WORDING.search(question) is not None


def enforce_requested_intent(
    plan: InvestigationPlan, question: str
) -> tuple[InvestigationPlan, ResearchIntent | None]:
    """Return the plan to review and the label it replaced, or None when nothing changed."""
    causal = ResearchIntent.CAUSAL_INFERENCE
    if plan.requested_intent == causal or not asks_for_cause(question):
        return plan, None
    corrected = InvestigationPlan.model_validate(
        {**plan.model_dump(mode="python"), "requested_intent": causal}
    )
    return corrected, plan.requested_intent
