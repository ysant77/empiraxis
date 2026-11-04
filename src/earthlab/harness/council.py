"""The council of one run: which checkpoint serves each seat, and the optional decision critic.

This module connects the engine to `identity` and `decision_critic`. With no registry the run
behaves as before. Nothing here changes a score, an outcome or an approval.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from earthlab.harness import decision_critic as critic
from earthlab.harness.claims import CostEvidence, ladder
from earthlab.harness.contracts import DecisionRecordV1, EvaluationReportV1
from earthlab.harness.identity import CheckpointV1, bindings_of, record_council
from earthlab.harness.method_review import MethodReviewRecordV1, _source
from earthlab.harness.seats import Seats
from earthlab.llm.client import ChatClient

PM, LEAD, DATA, ML = "product_manager", "geospatial_engineer", "data_specialist", "ml_engineer"
TEAM_SEATS = (PM, LEAD, DATA, ML)


@dataclass(frozen=True)
class CouncilOptions:
    """Run options. `registry` turns on role-binding records; `decision_critic` adds the critic."""

    registry: Mapping[str, CheckpointV1] | None = None
    decision_critic: bool = False


def seat_clients(seats: Seats, arm: str, with_critic: bool) -> dict[str, ChatClient]:
    """The client that serves each model seat of this arm."""
    if seats.client is None:
        return {}
    names = TEAM_SEATS if arm == "team" else (LEAD,)
    names = (*names, critic.CRITIC) if with_critic else names
    return {n: seats.role_clients.get(n, seats.client) for n in names}


class CouncilRecord:
    """What a run adds to its trace and result: role bindings, the summary and the critique."""

    def __init__(self, options: CouncilOptions):
        self.options = options
        self.summary: dict[str, Any] | None = None
        self.decision_critique: dict[str, Any] | None = None

    def open(self, seats: Seats, arm: str, method_review: bool) -> None:
        """Write the role bindings before the first model call. No registry, no records."""
        clients = seat_clients(seats, arm, method_review or self.options.decision_critic)
        if self.options.registry is not None and clients:
            self.summary = record_council(seats.trace, bindings_of(clients, self.options.registry))

    def critique(
        self, seats: Seats, report: EvaluationReportV1, decision: DecisionRecordV1, problem_id: str
    ) -> None:
        if self.options.decision_critic and seats.client is not None:
            self.decision_critique = critic.run_critic(
                seats, report, decision, problem_id, _source(seats)
            )

    def fields(self) -> dict[str, Any]:
        found = {"council": self.summary, "decision_critique": self.decision_critique}
        return {k: v for k, v in found.items() if v}


def review_outcome(
    review: MethodReviewRecordV1 | None, report: EvaluationReportV1 | None,
    decision: DecisionRecordV1 | None, used: dict[str, Any],
) -> dict[str, Any]:  # fmt: skip
    """The method-review record and the six claims. No role writes these."""
    if review is None:
        return {}
    out: dict[str, Any] = {"method_review": review.model_dump(mode="json")}
    if report is not None and decision is not None:
        case, seconds = review.proposal, float(used["training_seconds"])
        cost = CostEvidence(case.expected_benefit, case.compute_seconds, seconds)
        out["claims"] = ladder(
            report, decision.selected or report.reference, None, cost
        ).model_dump()
    return out
