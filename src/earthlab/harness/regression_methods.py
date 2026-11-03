"""PM2.5 regression whose research question needs a statistical and a neural model, both trained.

The family scenario trains a neural model only when the Lead chooses the small neural strategy.
This scenario asks an empirical question: does a compact neural model gain enough over a tuned
ridge to justify its cost? That needs both families, so when the Lead chooses either the
statistical or the small neural strategy, both are trained under one protocol. The Lead's
strategy is kept as the family it expects to adopt, and the trace says so. The Lead still sets
the neural configuration inside fixed limits, and can still choose deterministic or abstain,
which train nothing. The evaluator and the decision rule do not change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from earthlab.forecast.contracts import Assignment
from earthlab.forecast.pipeline import SOURCE
from earthlab.harness.acquire_step import AcquisitionConfig
from earthlab.harness.contracts import ExperimentPlanV1
from earthlab.harness.regression import PM25_PROBLEM
from earthlab.harness.regression_families import FamilyAdapter
from earthlab.harness.seats import Seats

COMPARED = ("statistical", "small_neural")
METHOD_PROBLEM = PM25_PROBLEM.model_copy(
    update={
        "problem_id": "pm25-method-comparison-6h",
        "success_criteria": (
            *PM25_PROBLEM.success_criteria,
            "persistence, a tuned ridge and a compact neural model all trained and scored on the "
            "same validation rows",
            "a more complex model is adopted only if its gain justifies its cost",
        ),
    }
)
OBJECTIVE = (
    "Compare deterministic persistence, a tuned statistical model and a compact neural model "
    "for regional PM2.5 six hours ahead on the historical NEA series. Both model families are "
    "trained. Decide whether the extra complexity gives enough benefit to adopt, from overall "
    "error, elevated-hour error, evaluation reliability and compute cost."
)


class MethodComparisonAdapter(FamilyAdapter):
    def __init__(
        self, run_dir: Path, source: Path = SOURCE, acquisition: AcquisitionConfig | None = None
    ):
        super().__init__(run_dir, source, acquisition)
        self.expected = ""

    def menu_for(self, strategy: str) -> type[BaseModel] | None:
        """The neural configuration is the Lead's choice whenever the families are compared."""
        return Assignment if strategy in COMPARED else None

    def train(self, plan: ExperimentPlanV1, seats: Seats) -> dict[str, Any]:
        lead = str(plan.config.get("strategy"))
        if lead not in COMPARED:
            return super().train(plan, seats)
        self.expected = lead
        seats.trace.append(
            "family_comparison", "runtime", lead_strategy=lead,
            trained=["ridge tuned on rolling-origin train folds", str(plan.config["architecture"])],
            reason="the research question needs both families; the Lead's strategy is kept as "
            "the family it expects to adopt",
        )  # fmt: skip
        both = plan.model_copy(update={"config": plan.config | {"strategy": "small_neural"}})
        out = super().train(both, seats)
        return {**out, "lead_strategy": lead}


def method_adapter(run_dir: Path) -> MethodComparisonAdapter:
    return MethodComparisonAdapter(run_dir)


__all__ = ["COMPARED", "METHOD_PROBLEM", "OBJECTIVE", "MethodComparisonAdapter", "method_adapter"]
