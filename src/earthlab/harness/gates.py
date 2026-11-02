"""Deterministic refusals before any work runs. Each returns a code, never a free judgement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from earthlab.harness.contracts import (
    DatasetProfileV1,
    ExperimentPlanV1,
    ProblemSpecV1,
    ResearchRequestV1,
)

HLS_BANDS = ("blue", "green", "red", "nir_narrow", "swir1", "swir2")
MIN_POSITIVE_RATE = 0.005
MIN_ROWS = 1000
SEGMENTATION_MAX_RESOLUTION_M = 30.0
_CAUSAL = re.compile(
    r"\b(?:what|who|did|does|do|which)\b[^.?]{0,80}\b(?:caus\w*|responsible|to blame)\b"
    r"|\b(?:caused by|because of|attribut\w+ to|due to)\b",
    re.IGNORECASE,
)


class Code(StrEnum):
    NO_USABLE_DATA = "no_usable_data"
    MISSING_LABELS = "missing_labels"
    WRONG_VARIABLE = "wrong_variable"
    WRONG_UNIT = "wrong_unit"
    TEMPORAL_LEAKAGE = "temporal_leakage"
    INCOMPATIBLE_INPUTS = "incompatible_inputs"
    EXTREME_IMBALANCE = "extreme_imbalance"
    UNSUPPORTED_CAUSAL = "unsupported_causal_attribution"
    UNSUPPORTED_METHOD = "unsupported_method"
    OVER_BUDGET = "over_budget"
    METHOD_REVIEW = "method_review"


@dataclass(frozen=True)
class Refusal:
    code: Code
    detail: str


def check_request(request: ResearchRequestV1) -> list[Refusal]:
    if _CAUSAL.search(request.objective):
        return [Refusal(Code.UNSUPPORTED_CAUSAL, "this harness cannot establish a cause")]
    return []


def check_problem(problem: ProblemSpecV1, profile: DatasetProfileV1) -> list[Refusal]:
    out = []
    if profile.usable_rows < MIN_ROWS:
        out.append(Refusal(Code.NO_USABLE_DATA, f"{profile.usable_rows} usable rows"))
    if profile.variable != problem.variable:
        out.append(Refusal(Code.WRONG_VARIABLE, f"the data holds {profile.variable}"))
    if profile.unit != problem.unit:
        out.append(Refusal(Code.WRONG_UNIT, f"the data unit is {profile.unit}"))
    if not profile.labels_present:
        out.append(Refusal(Code.MISSING_LABELS, "no target labels with provenance"))
    rate = profile.positive_rate
    if problem.kind == "classification" and rate is not None and rate < MIN_POSITIVE_RATE:
        out.append(Refusal(Code.EXTREME_IMBALANCE, f"positive rate {rate:.5f} in train"))
    return out


def check_segmentation(profile: DatasetProfileV1) -> list[Refusal]:
    """What a pretrained segmentation model needs. MCD64A1 meets none of it."""
    out = []
    missing = [band for band in HLS_BANDS if band not in profile.bands]
    if missing:
        out.append(Refusal(Code.INCOMPATIBLE_INPUTS, f"missing bands: {', '.join(missing)}"))
    size = profile.resolution_m
    if size is None or size > SEGMENTATION_MAX_RESOLUTION_M:
        out.append(Refusal(Code.INCOMPATIBLE_INPUTS, f"resolution {size} m"))
    if "reference mask" not in profile.label_provenance:
        out.append(Refusal(Code.MISSING_LABELS, "no independent reference masks"))
    return out


def check_plan(
    plan: ExperimentPlanV1, profile: DatasetProfileV1, allowed: tuple[str, ...], estimate: float
) -> list[Refusal]:
    out = []
    for method in plan.methods:
        if method not in allowed:
            out.append(Refusal(Code.UNSUPPORTED_METHOD, f"{method} is not registered here"))
    if plan.input_offset_hours < profile.availability_latency_hours:
        detail = f"inputs at T-{plan.input_offset_hours} h are not yet available"
        out.append(Refusal(Code.TEMPORAL_LEAKAGE, detail))
    if estimate > plan.budget.max_training_seconds:
        detail = f"estimate {estimate:.0f} s over {plan.budget.max_training_seconds:.0f} s"
        out.append(Refusal(Code.OVER_BUDGET, detail))
    return out
