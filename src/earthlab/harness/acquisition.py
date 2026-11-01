"""The deterministic decision to acquire a product, in a fixed order of steps.

Order: availability query, suitability, marginal value, smallest request, approval, then
(after a transfer) hash, QA and registry. A step that fails stops the rest. A catalogue entry
grants nothing. Code decides; a model may only propose the task and the extent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field

from earthlab.cases.models import BoundingBox
from earthlab.contracts import Strict
from earthlab.harness.suitability import (
    AlignmentReportV1,
    DatasetSuitabilityV1,
    JoinPlanV1,
    preflight,
)

PILOT_MAX_DAYS = 31
PILOT_MAX_BYTES = 250_000_000
POST_TRANSFER = ("hash_verification", "quality_assurance", "registry")
Step = Literal[
    "availability_query", "suitability", "marginal_value", "smallest_request", "approval"
]
Value = Literal["demonstrated", "unproven", "none"]
Decision = Literal[
    "already_local", "refuse", "needs_approval", "pilot_needs_approval", "proceed_to_transfer"
]
ApprovalState = Literal["signed", "chat_only", "none", "denied"]


class BaselineGap(Strict):
    """A measured gap the new product could close. None means no one measured it."""

    metric: str
    baseline_value: float | None = None
    best_possible_gain: float | None = None


class Extent(Strict):
    area: BoundingBox
    start: datetime
    end: datetime
    bytes_estimate: int = Field(ge=0)


class StepResult(Strict):
    step: Step
    passed: bool
    detail: str


class AcquisitionDecisionV1(Strict):
    schema_version: Literal["1"] = "1"
    dataset_id: str
    task: str
    decision: Decision
    value: Value
    steps: tuple[StepResult, ...]
    request: Extent | None = None
    alignment: AlignmentReportV1 | None = None
    post_transfer_steps: tuple[str, ...] = POST_TRANSFER
    route: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


def marginal_value(gap: BaselineGap | None) -> Value:
    """Demonstrated only when a measured baseline leaves room. Unknown is unproven."""
    if gap is None or gap.best_possible_gain is None:
        return "unproven"
    return "demonstrated" if gap.best_possible_gain > 0 else "none"


def _overlap(a0: float, a1: float, b0: float, b1: float) -> tuple[float, float] | None:
    lo, hi = max(a0, b0), min(a1, b1)
    return (lo, hi) if lo < hi else None


def _cut_area(wanted: BoundingBox, task: BoundingBox) -> BoundingBox | None:
    lon = _overlap(wanted.min_lon, wanted.max_lon, task.min_lon, task.max_lon)
    lat = _overlap(wanted.min_lat, wanted.max_lat, task.min_lat, task.max_lat)
    if lon is None or lat is None:
        return None
    return BoundingBox(min_lon=lon[0], min_lat=lat[0], max_lon=lon[1], max_lat=lat[1])


def _span(box: BoundingBox) -> float:
    return (box.max_lon - box.min_lon) * (box.max_lat - box.min_lat)


def smallest_request(
    wanted: Extent, plan: JoinPlanV1, value: Value, full_bytes: int | None
) -> Extent | None:
    """Cut the wanted extent to the task area and window. A pilot is also capped in time."""
    area = _cut_area(wanted.area, plan.aoi)
    start, end = max(wanted.start, plan.window_start), min(wanted.end, plan.window_end)
    if area is None or start >= end:
        return None
    if value == "unproven":
        end = min(end, start + timedelta(days=PILOT_MAX_DAYS))
    share = (_span(area) / _span(wanted.area)) * ((end - start) / (wanted.end - wanted.start))
    base = full_bytes if full_bytes is not None else wanted.bytes_estimate
    size = round(base * share)
    return Extent(area=area, start=start, end=end, bytes_estimate=size)


def _approval_step(state: ApprovalState, covered: bool) -> StepResult:
    if covered or state == "signed":
        return StepResult(step="approval", passed=True, detail="a signed record covers it")
    if state == "denied":
        return StepResult(step="approval", passed=False, detail="a human denied the request")
    note = "chat approval has no signed record" if state == "chat_only" else "no approval"
    return StepResult(step="approval", passed=False, detail=note)


def _stop(
    profile: DatasetSuitabilityV1, task: str, steps: list[StepResult], value: Value, why: str
) -> AcquisitionDecisionV1:
    return AcquisitionDecisionV1(
        dataset_id=profile.dataset_id, task=task, decision="refuse", value=value,
        steps=tuple(steps), reasons=(why,),
    )  # fmt: skip


def decide(
    task: str,
    profile: DatasetSuitabilityV1,
    plan: JoinPlanV1,
    gap: BaselineGap | None,
    wanted: Extent,
    approval: ApprovalState = "none",
    covered_by_existing: bool = False,
) -> AcquisitionDecisionV1:
    """One decision for one product and one task. Refusal is a normal result."""
    steps: list[StepResult] = []
    local = profile.local_state == "verified"
    steps.append(StepResult(step="availability_query", passed=True, detail=profile.local_state))
    if local:
        return AcquisitionDecisionV1(
            dataset_id=profile.dataset_id, task=task, decision="already_local",
            value=marginal_value(gap), steps=tuple(steps), reasons=("a verified copy exists",),
        )  # fmt: skip
    # The product is not local, so the join is judged on its catalogue facts alone.
    facts = profile.model_copy(update={"local_state": "verified", "local_sha256": "0" * 64})
    alignment = preflight(plan, [facts])
    blocking = [f.detail for f in alignment.findings if f.blocking]
    steps.append(StepResult(step="suitability", passed=not blocking, detail="; ".join(blocking)))
    if blocking:
        return _stop(profile, task, steps, "none", "the product does not fit the task").model_copy(
            update={"alignment": alignment}
        )
    value = marginal_value(gap)
    steps.append(StepResult(step="marginal_value", passed=value != "none", detail=value))
    if value == "none":
        return _stop(profile, task, steps, value, "the baseline leaves no room to gain")
    request = smallest_request(wanted, plan, value, profile.bytes_estimate)
    steps.append(StepResult(step="smallest_request", passed=request is not None, detail=""))
    if request is None:
        return _stop(profile, task, steps, value, "the extent has no overlap with the task")
    ok = _approval_step(approval, covered_by_existing)
    steps.append(ok)
    pilot = value == "unproven"
    if ok.passed:
        decision: Decision = "proceed_to_transfer"
    else:
        decision = "pilot_needs_approval" if pilot else "needs_approval"
    route = () if ok.passed else ("data_specialist", "geospatial_lead", "product_manager", "human")
    return AcquisitionDecisionV1(
        dataset_id=profile.dataset_id, task=task, decision=decision, value=value,
        steps=tuple(steps), request=request, alignment=alignment, route=route,
        reasons=tuple(r for r in (ok.detail,) if not ok.passed),
    )  # fmt: skip
