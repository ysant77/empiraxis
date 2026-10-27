"""Reject claim statements that go beyond what PM2.5 observations alone can support."""

from __future__ import annotations

import re

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "causal attribution needs meteorology, hotspot and transport evidence",
        re.compile(
            r"\b(caus\w*|due to|because of|attribut\w*|responsible|resulted? from|"
            r"originat\w*|came from|blown|transported|driven by)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "forecasts are out of scope for a retrospective dataset",
        re.compile(r"\b(will|forecast\w*|predict\w*|expect\w*|likely to)\b", re.IGNORECASE),
    ),
    (
        "health or safety advice is out of scope",
        re.compile(
            r"\b(health\w*|unhealthy|hazardous|safe|unsafe|danger\w*|"
            r"advis\w*|should (stay|avoid|wear))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "regional values are not station or coordinate measurements",
        re.compile(r"\b(station|sensor|monitor at|latitude|longitude)\b", re.IGNORECASE),
    ),
    (
        "PSI and AQI are different indices from PM2.5",
        re.compile(r"\b(PSI|AQI)\b"),
    ),
)


def language_violation(statement: str) -> str | None:
    """Return the first rule the statement breaks, or None."""
    for reason, pattern in _RULES:
        if pattern.search(statement):
            return reason
    return None
