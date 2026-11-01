"""Profile records. A value that no run recorded is None, never zero."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict

ModelRole = Literal["product_manager", "orchestrator", "geospatial_engineer"]
MODEL_ROLES: tuple[ModelRole, ...] = ("product_manager", "orchestrator", "geospatial_engineer")


class RoleUsage(Strict):
    """Model calls of one role in one run.

    Token and wall sums cover only the calls that reported the field. `calls_with_usage` and
    `calls_with_wall` say how many that was, so a partial sum is never read as a full one.
    """

    role: ModelRole
    model_calls: int = Field(ge=0)
    calls_with_usage: int = Field(ge=0)
    calls_with_wall: int = Field(ge=0)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    wall_seconds: float | None = None


class CostRecord(Strict):
    """Local compute is kept apart from billed provider cost."""

    local_model_wall_seconds: float | None
    local_energy_wh: float | None = None  # not metered on the recorded runs
    billed_provider_cost_usd: float | None  # None: no provider bill exists or none was measured
    billed_cost_note: str
    estimated_cost_usd: float | None  # the runtime's own price-table estimate, not a bill


class RunProfile(Strict):
    run_id: str | None
    stage: str
    scenario_id: str
    arm: str
    started_utc: str
    source_commit: str
    exit_code: int | None
    manifest_wall_seconds: float | None
    artifacts: Literal["complete", "no_run_folder", "no_trace", "no_result"]
    status: str | None
    expected: str
    goal_satisfied: bool | None  # None: not decidable from the record
    abstained: bool | None
    failed: bool | None
    answer_revisions: int | None
    guard_loaded_at_start: bool | None
    system_wired_peak_mb: int | None
    swap_used_peak_mb: int | None
    roles: tuple[RoleUsage, ...]
    cost: CostRecord

    def usage(self, role: ModelRole) -> RoleUsage | None:
        return next((u for u in self.roles if u.role == role), None)


class Anomaly(Strict):
    kind: str
    detail: str
