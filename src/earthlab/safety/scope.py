"""Deterministic scope rules for questions and final answers.

EarthLab reports observations. It does not give health or safety advice, judge air
quality, take political positions, forecast, or assert causes. These rules run with or
without the safety model, so a weak or missing classifier never widens the scope.
"""

from __future__ import annotations

import re

_I = re.IGNORECASE
_NEGATION = re.compile(
    r"\b(not|no|cannot|can't|cannot be|does not|do not|did not|without|neither|nor|unable)\b", _I
)
_NEGATION_WINDOW = 60

_ADVICE = re.compile(
    r"\b(is it safe|safe to|should (i|we|you|people|residents|they)|stay indoors|wear (a )?mask|"
    r"masks?|asthma\w*|medic\w*|medicine|symptom\w*|doctor|hospital|disease|patients?|"
    r"pregnan\w*|health\w*|unhealthy|hazardous|dangerous|harmful)\b",
    _I,
)
_POLITICS = re.compile(
    r"\b(election\w*|political|(?<!-)party|(?<!-)parties|government\w*|minister\w*|blame\w*|"
    r"war|wars|military|retaliat\w*|sanction\w*|boycott\w*|protest\w*)\b",
    _I,
)
_FORECAST_REQUEST = re.compile(r"\b(forecast\w*|predict\w*|next (year|month|week)|in 2027)\b", _I)
_CAUSE = re.compile(
    r"\b(caused|causes|cause of|due to|because|resulted from|responsible for|"
    r"attributed to|came from|blown from|driven by|smoke from|sent smoke)\b",
    _I,
)
# A cause word about missing data or methods ("blocked because the dataset is unavailable")
# is not a claim about what caused an observation.
_AVAILABILITY = re.compile(
    r"\b(unavailab\w*|not available|not implemented|not pinned|approval|missing|no data)\b", _I
)
_CLAUSE_CHARS = 80
_FORECAST_CLAIM = re.compile(
    r"\b(will (rise|fall|increase|decrease|return|happen|be)|forecast)\b", _I
)


def _asserted(pattern: re.Pattern[str], text: str) -> bool:
    """True if any match is not preceded by a nearby negation ('cannot show it caused')."""
    for match in pattern.finditer(text):
        window = text[max(0, match.start() - _NEGATION_WINDOW) : match.start()]
        if not _NEGATION.search(window):
            return True
    return False


def _asserted_cause(text: str) -> bool:
    for match in _CAUSE.finditer(text):
        before = text[max(0, match.start() - _NEGATION_WINDOW) : match.start()]
        clause = text[match.end() : match.end() + _CLAUSE_CHARS].split(".")[0]
        if not _NEGATION.search(before) and not _AVAILABILITY.search(clause):
            return True
    return False


def question_out_of_scope(question: str) -> str | None:
    """Reason to refuse a question before any model runs, or None."""
    if _ADVICE.search(question):
        return "health, safety or air-quality advice is out of scope"
    if _POLITICS.search(question):
        return "political, conflict and blame questions are out of scope"
    if _FORECAST_REQUEST.search(question):
        return "forecasts are out of scope; EarthLab studies past observations"
    return None


def answer_out_of_scope(answer: str) -> str | None:
    """Reason to withhold a final answer, or None. Negated statements are allowed."""
    if _asserted(_ADVICE, answer):
        return "the answer gives health, safety or air-quality judgements"
    if _POLITICS.search(answer):
        return "the answer takes up political or conflict topics"
    if _asserted_cause(answer):
        return "the answer asserts a cause the data cannot show"
    if _asserted(_FORECAST_CLAIM, answer):
        return "the answer makes a forecast"
    return None
