"""Typed records for one delegation: Geospatial Lead -> data specialist -> Geospatial Lead.

A model proposes; code validates. The ticket fixes owner, input, checks, limits and paths
before any work starts. A proposal has no field that can grant a permission or mark a
result as passed: extra fields are refused.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.workflow.contracts import SHA256, TASK_ID, RoleCall

Artifact = Literal["qa_sensitivity_table_v1"]
DelegationStatus = Literal["verified", "needs_revision", "failed", "budget_exhausted"]


class CheckProposal(Strict):
    """What the Lead model submits: which months need a QA-sensitivity check, and why."""

    months: tuple[str, ...] = Field(min_length=1, max_length=4)
    reason: str = Field(min_length=5, max_length=300)


class SpecialistTicketV1(Strict):
    schema_version: Literal["1"] = "1"
    task_id: str = Field(pattern=TASK_ID)
    parent_task_id: str = Field(pattern=TASK_ID)
    owner: Literal["data_specialist"] = "data_specialist"
    objective: str = Field(min_length=5, max_length=300)
    case_id: str
    input_sha256: str = Field(pattern=SHA256)  # the parent run's trace head
    months: tuple[str, ...] = Field(min_length=1, max_length=4)
    qa_policies: tuple[str, ...] = Field(min_length=1)
    acceptance_checks: tuple[str, ...] = Field(min_length=1)
    priority: Literal["normal"] = "normal"
    artifact: Artifact = "qa_sensitivity_table_v1"
    allowed_tools: tuple[str, ...] = Field(min_length=1)
    allowed_paths: tuple[str, ...] = ()  # this task writes no repository file
    human_approval_required: Literal[False] = False
    max_model_calls: int = Field(gt=0)
    max_tool_calls: int = Field(gt=0)
    max_seconds: float = Field(gt=0)
    max_cost_usd: float = Field(ge=0)
    deadline_utc: str


class QaRowV1(Strict):
    month: str = Field(max_length=7)
    qa_policy: str = Field(max_length=20)
    valid_fraction: float = Field(ge=0, le=1)
    gate_passed: bool
    area_ha: float | None = Field(default=None, ge=0)


class QaTableProposal(Strict):
    """What the specialist model submits. Code recomputes every row."""

    rows: tuple[QaRowV1, ...] = Field(min_length=1, max_length=24)


class CheckResult(Strict):
    name: str
    passed: bool
    detail: str = ""


class AcceptanceV1(Strict):
    """The result of the ticket's checks. Only code writes this record."""

    task_id: str = Field(pattern=TASK_ID)
    passed: bool
    checks: tuple[CheckResult, ...]


class SpecialistResultV1(Strict):
    schema_version: Literal["1"] = "1"
    task_id: str = Field(pattern=TASK_ID)
    artifact: Artifact = "qa_sensitivity_table_v1"
    rows: tuple[QaRowV1, ...]
    rows_sha256: str = Field(pattern=SHA256)
    source_sha256: tuple[str, ...]
    acceptance: AcceptanceV1
    author: RoleCall


class LeadReview(Strict):
    """What the Lead model submits. It can send a passed table back, never pass a failed one."""

    accept: bool
    note: str = Field(min_length=3, max_length=300)
