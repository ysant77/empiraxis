"""Typed hand-off records between the product manager, the code controller and the engineer.

The product manager model proposes a `BriefProposal` through one schema-only tool. Code
validates it into a `ProductBriefV1`, turns that into an `EngineeringTaskV1` for the
Geospatial Engineer, maps the engineer's run into an `EngineeringReplyV1`, and returns a
`ManagerResultV1` built from verified findings only. Every record is hashed in the trace.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.planning.vocab import ResearchIntent

TASK_ID = r"^[a-z0-9][a-z0-9._-]{0,79}$"
SHA256 = r"^[0-9a-f]{64}$"

Route = Literal["engineer", "needs_input", "out_of_scope"]
Topology = Literal["combined"]  # one PM call also proposes the route; code decides it
WorkflowStatus = Literal[
    "verified",
    "partial",
    "answer_unverified",
    "abstained",
    "no_supported_findings",
    "budget_exhausted",
    "provider_error",
    "refused",
    "needs_input",
    "out_of_scope",
    "failed",
]


class BriefProposal(Strict):
    """What the product manager model submits. It names no dataset, value or method."""

    route: Route
    case_id: str | None = Field(default=None, max_length=80)
    normalized_question: str = Field(min_length=5, max_length=400)
    intent: ResearchIntent
    target_quantity: str | None = Field(default=None, max_length=80)
    period_start: datetime | None = None
    period_end: datetime | None = None
    constraints: tuple[str, ...] = Field(default=(), max_length=6)
    clarifications_needed: tuple[str, ...] = Field(default=(), max_length=3)


class RoleCall(Strict):
    """The configured model for a role call, and what the server says it served."""

    role_id: Literal["product_manager", "geospatial_engineer"]
    provider: str
    model: str
    logical_model: str
    served_model: str | None = None


class ProductBriefV1(Strict):
    schema_version: Literal["1"] = "1"
    task_id: str = Field(pattern=TASK_ID)
    request_sha256: str = Field(pattern=SHA256)  # the request text stays in the private trace
    topology: Topology = "combined"
    brief: BriefProposal
    author: RoleCall


class EngineeringTaskV1(Strict):
    schema_version: Literal["1"] = "1"
    task_id: str = Field(pattern=TASK_ID)
    parent_task_id: str = Field(pattern=TASK_ID)
    brief_sha256: str = Field(pattern=SHA256)
    role_id: Literal["geospatial_engineer"] = "geospatial_engineer"
    objective: str = Field(min_length=5, max_length=400)
    case_id: str
    allowed_dataset_ids: tuple[str, ...] = Field(min_length=1)
    allowed_method_ids: tuple[str, ...] = Field(min_length=1)
    max_model_calls: int = Field(gt=0)
    max_tool_calls: int = Field(gt=0)
    max_seconds: float = Field(gt=0)
    max_cost_usd: float = Field(ge=0)
    approval_scope: Literal["read-only pinned files"] = "read-only pinned files"
    expected_output: Literal["reviewed plan and verified claims"] = (
        "reviewed plan and verified claims"
    )


class EngineeringReplyV1(Strict):
    """The engineer's run as the controller saw it, from the run record, not model text."""

    schema_version: Literal["1"] = "1"
    task_id: str = Field(pattern=TASK_ID)
    status: WorkflowStatus
    plan_sha256: tuple[str, ...]
    critic_verdicts: tuple[str, ...]
    supported_finding_ids: tuple[str, ...]
    limitation_reasons: tuple[str, ...]
    elapsed_ms: int = Field(ge=0)
    author: RoleCall


class ManagerResultV1(Strict):
    schema_version: Literal["1"] = "1"
    task_id: str = Field(pattern=TASK_ID)
    status: WorkflowStatus
    verified_finding_refs: tuple[str, ...] = ()
    typed_limitations: tuple[str, ...] = ()
    report_text: str = ""
    report_source: Literal["pm_model", "engineer", "rendered", "none"] = "none"
    source_hashes: tuple[str, ...] = ()
    followup_questions: tuple[str, ...] = ()
