"""The lifecycle and its authority. State is folded from the hash-chained trace.

The controller names the actor, not a model. Only the evaluator enters `evaluated`. Only a
valid signed human record enters `approved` or `denied`. Any open state can end in a refusal,
an abstention or a failure, and an ended run does not move again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from earthlab.team.resources import ResourceApprovalV1, key_matches, sign
from earthlab.trace import RunTrace

State = Literal[
    "requested", "scoped", "profiled", "acquired", "planned", "executing", "evaluated", "reviewed",
    "forwarded", "approved", "denied", "expired", "abstained", "refused", "failed",
]  # fmt: skip
Actor = Literal["controller", "evaluator", "human"]
MOVE = "harness_transition"
ENDINGS = frozenset({"abstained", "refused", "failed"})
FINAL: frozenset[str] = ENDINGS | {"approved", "denied", "expired"}
MOVES: dict[str, dict[str, Actor]] = {
    "requested": {"scoped": "controller"},
    "scoped": {"profiled": "controller"},
    "profiled": {"planned": "controller", "acquired": "controller"},
    "acquired": {"planned": "controller"},  # an optional, approved acquisition
    "planned": {"executing": "controller"},
    "executing": {"evaluated": "evaluator"},
    "evaluated": {"reviewed": "controller"},
    "reviewed": {"forwarded": "controller", "planned": "controller"},
    "forwarded": {"approved": "human", "denied": "human", "expired": "controller"},
}


class IllegalTransition(ValueError):
    """The move or the actor breaks the lifecycle. Nothing was written."""


class Lifecycle:
    def __init__(self, run_dir: Path, trace: RunTrace | None = None):
        self.run_dir = run_dir
        self.trace = trace or RunTrace(run_dir / "trace.jsonl")

    @property
    def state(self) -> str:
        last = "requested"
        for entry in self.trace.records():
            if entry["event"] == MOVE:
                last = entry["data"]["to"]
        return last

    def move(self, to: State, actor: Actor, **evidence: Any) -> None:
        now = self.state
        if now in FINAL:
            raise IllegalTransition(f"{now} is final")
        if to in ENDINGS:
            allowed: Actor = "controller"
        elif to in MOVES.get(now, {}):
            allowed = MOVES[now][to]
        else:
            raise IllegalTransition(f"{now} cannot move to {to}")
        if actor != allowed:
            raise IllegalTransition(f"{actor} cannot move {now} to {to}")
        self.trace.append(MOVE, actor, **{"from": now, "to": to}, **evidence)

    def human_decision(self, approval: ResourceApprovalV1, record_sha256: str, key: str) -> None:
        """A signed decision on these exact bytes, or an expiry. Anything else is refused."""
        if self.state != "forwarded":
            raise IllegalTransition("only a forwarded experiment can be decided")
        if not key_matches(key) or approval.signature != sign(approval, key):
            raise IllegalTransition("the signature is not valid")
        if approval.request_sha256 != record_sha256:
            raise IllegalTransition("the approval names different evidence")
        to: State = "approved" if approval.approved else "denied"
        self.move(to, "human", request_sha256=record_sha256, at=approval.decided_at_utc.isoformat())

    def expire(self, deadline: datetime) -> bool:
        if self.state == "forwarded" and datetime.now(UTC) > deadline:
            self.move("expired", "controller", deadline=deadline.isoformat())
            return True
        return False
