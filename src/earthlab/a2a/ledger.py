"""Idempotency keys and quotas for one server process, held in memory.

A peer's `request_id` maps to one server task. The first send claims the key and takes a
running slot; a repeat with the same digest gets that task back and starts nothing. A slot
is released only when the engineer's worker has really stopped, so a cancel does not free
capacity while a run is still spending. The event loop is the only writer of claims;
`release` also arrives from there, through the worker's done callback.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass


class QuotaExhausted(Exception):
    """The peer has no running slot or task allowance left. Nothing was claimed."""


class RequestConflict(Exception):
    """The request ID was used before for a different payload."""


@dataclass(frozen=True)
class Quota:
    max_running: int = 1
    max_tasks: int = 20


@dataclass(frozen=True)
class Ticket:
    """A claimed request ID and the server IDs for its one task."""

    owner: str
    request_id: str
    digest: str
    task_id: str
    context_id: str


class RequestLedger:
    def __init__(self, quota: Quota):
        self._quota = quota
        self._tickets: dict[tuple[str, str], Ticket] = {}
        self._running: Counter[str] = Counter()
        self._total: Counter[str] = Counter()

    def claim(
        self, owner: str, request_id: str, digest: str, context_id: str | None
    ) -> tuple[Ticket, bool]:
        """The ticket and whether it is new. Keys are per peer, so peers cannot collide."""
        found = self._tickets.get((owner, request_id))
        if found is not None:
            if found.digest != digest:
                raise RequestConflict(request_id)
            return found, False
        if self._running[owner] >= self._quota.max_running:
            raise QuotaExhausted(f"running task limit {self._quota.max_running} reached")
        if self._total[owner] >= self._quota.max_tasks:
            raise QuotaExhausted(f"task limit {self._quota.max_tasks} reached")
        ticket = Ticket(
            owner, request_id, digest, str(uuid.uuid4()), context_id or str(uuid.uuid4())
        )
        self._tickets[(owner, request_id)] = ticket
        self._running[owner] += 1
        self._total[owner] += 1
        return ticket, True

    def release(self, owner: str) -> None:
        """Return one running slot. The task allowance stays spent."""
        self._running[owner] -= 1

    def running(self, owner: str) -> int:
        return self._running[owner]
