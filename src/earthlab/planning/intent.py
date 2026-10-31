"""What the question asks for, decided by the runtime and not by the model's plan.

The critic reads `requested_intent` from the plan. If the model labels a causal question as
non-causal, the critic cannot require the causal abstention. This module looks for causal
wording in the question itself and corrects the label before the review. The check only
moves a plan toward the causal intent, never away from it: a false match costs a needless
abstention, a missed match lets claims stand where the question asked for a cause.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

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


NEA_ZONE = "Asia/Singapore"
_MONTH_NAMES = [
    "january",
    "february",
    "march",
    "april",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
_MONTH_NUMBER = {name: i for i, name in enumerate(_MONTH_NAMES, start=1)}
_MONTH_NUMBER |= {name: number + (number > 4) for name, number in _MONTH_NUMBER.items()}
_MONTH_WORD = "|".join(_MONTH_NAMES)
_NAMED = re.compile(rf"\b({_MONTH_WORD})\b", re.IGNORECASE)
_NAMED_DAY = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTH_WORD})\b|\b(?:{_MONTH_WORD})\s+\d{{1,2}}\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def asked_window(question: str, zone: str = NEA_ZONE) -> tuple[datetime, datetime] | None:
    """The whole months a question names, end excluded, or None when it does not fix them.

    A named day, a second year or no month gives None: the check then does not apply.
    """
    years = set(_YEAR.findall(question))
    months = [_MONTH_NUMBER[m.lower()] for m in _NAMED.findall(question)]
    if len(years) != 1 or not months or _NAMED_DAY.search(question):
        return None
    year, tz = int(years.pop()), ZoneInfo(zone)
    last = max(months)
    end = datetime(year + last // 12, last % 12 + 1, 1, tzinfo=tz)
    return datetime(year, min(months), 1, tzinfo=tz), end


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
