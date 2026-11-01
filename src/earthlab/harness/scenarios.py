"""The registered scenarios. Each pairs a fixed problem with its adapter."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from earthlab.harness.contracts import ProblemSpecV1, ResearchRequestV1
from earthlab.harness.engine import Adapter, Arm, run_harness
from earthlab.harness.regression import PM25_PROBLEM, RegressionAdapter
from earthlab.llm.client import ChatClient

SUMMARY = (
    "state", "kind", "workflow_class", "model_changed_the_plan", "recommendation",
    "comparison", "acceptance", "refusal_codes", "limitations", "usage",
)  # fmt: skip
Scenario = tuple[str, ProblemSpecV1, Callable[[Path], Adapter]]
SCENARIOS: dict[str, Scenario] = {
    "pm25-regression": (
        "Can historical regional NEA PM2.5 observations predict concentration six hours "
        "ahead more accurately than persistence?",
        PM25_PROBLEM,
        RegressionAdapter,
    ),
}


def run_scenario(name: str, arm: Arm, run_dir: Path, client: ChatClient | None) -> dict[str, Any]:
    objective, problem, make = SCENARIOS[name]
    request = ResearchRequestV1(request_id=name, objective=objective)
    return run_harness(arm, request, problem, make(run_dir), run_dir, client)
