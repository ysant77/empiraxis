"""Filter events by audience and withhold any summary that looks secret or held-out.

The check fails closed: an event whose text matches a blocked pattern is withheld from
every audience below internal, even if its visibility says public.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from earthlab.events.contract import VISIBILITY_ORDER, EventV1, Visibility

BLOCKED_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),  # provider secret keys
    re.compile(r"(?i)\bapi[_ -]?key\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"(?i)\b(?:password|secret|token)\s*[:=]"),
    re.compile(r"\bHO-[A-Za-z0-9]+"),  # held-out scenario ids
    re.compile(r"(?i)<think>|chain[- ]of[- ]thought"),
)


def text_is_safe(text: str) -> bool:
    return not any(p.search(text) for p in BLOCKED_PATTERNS)


def visible_events(events: Iterable[EventV1], audience: Visibility) -> tuple[list[EventV1], int]:
    """Return the events this audience may see and the count withheld from it."""
    allowed = set(VISIBILITY_ORDER[: VISIBILITY_ORDER.index(audience) + 1])
    shown: list[EventV1] = []
    withheld = 0
    for event in events:
        safe = audience is Visibility.INTERNAL or text_is_safe(event.message_summary)
        if event.display_visibility in allowed and safe:
            shown.append(event)
        else:
            withheld += 1
    return shown, withheld
