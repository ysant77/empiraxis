"""The deterministic acceptance check for the specialist closing step, and its dev tickets.

A specialist closes cleanly when its tool calls are exactly the ticket tool, then
`submit_note`. No model judges this. The tuning tool in `tools/prompt_optimizer` scores
candidate prompts with this check only.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from earthlab.contracts import Strict

FINISH = "submit_note"


class DevTicket(Strict):
    ticket_id: str
    prompt_key: Literal["data", "ml"]
    owner: str
    tool: str
    ticket: dict[str, Any]


class DevTickets(Strict):
    version: int
    purpose: str
    tickets: tuple[DevTicket, ...] = Field(min_length=1)


def closes_cleanly(calls: Sequence[str], tool: str) -> bool:
    """True only for one ticket-tool call, then one `submit_note` call, and nothing else."""
    return list(calls) == [tool, FINISH]


def load_dev_tickets(path: Path) -> DevTickets:
    return DevTickets.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
