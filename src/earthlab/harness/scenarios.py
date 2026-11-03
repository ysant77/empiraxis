"""The registered scenarios. Each pairs a fixed problem with its adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from earthlab.harness.acquire_step import AcquisitionConfig
from earthlab.harness.classify import EXCEED_PROBLEM, ClassificationAdapter
from earthlab.harness.contracts import ProblemSpecV1, ResearchRequestV1
from earthlab.harness.engine import Adapter, Arm, run_harness
from earthlab.harness.raster import BURN_PROBLEM, RasterAdapter, segmentation_request
from earthlab.harness.regression import PM25_PROBLEM, RegressionAdapter
from earthlab.harness.regression_families import FAMILY_PROBLEM, OBJECTIVE, family_adapter
from earthlab.harness.variants import PROMOTED, PromptVariant
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
    "pm25-exceedance": (
        "Can the same historical observations support a reliable future PM2.5 "
        "threshold-exceedance classifier?",
        EXCEED_PROBLEM,
        ClassificationAdapter,
    ),
    "burned-area-method": (
        "For this burned-area study window, should the system use a deterministic raster "
        "method, a pretrained segmentation model, or abstain?",
        BURN_PROBLEM,
        RasterAdapter,
    ),
    "pm25-family-comparison": (OBJECTIVE, FAMILY_PROBLEM, family_adapter),
    "burned-area-segmentation": (
        "Segment the burned area in this study window with a pretrained model.",
        BURN_PROBLEM,
        segmentation_request,
    ),
}


def run_scenario(
    name: str, arm: Arm, run_dir: Path, client: ChatClient | None, *,
    role_clients: Mapping[str, ChatClient] | None = None, variant: PromptVariant = PROMOTED,
    method_review: bool = False, acquisition: AcquisitionConfig | None = None,
) -> dict[str, Any]:  # fmt: skip
    objective, problem, make = SCENARIOS[name]
    request = ResearchRequestV1(request_id=name, objective=objective)
    adapter = make(run_dir)
    if acquisition is not None:
        if not hasattr(adapter, "acquisition"):
            raise ValueError(f"{name} has no acquisition step")
        adapter.acquisition = acquisition
    return run_harness(
        arm, request, problem, adapter, run_dir, client,
        role_clients=role_clients, variant=variant, method_review=method_review,
    )  # fmt: skip
