"""Typed records on the A2A wire: the peer's task request and the final run report.

A peer names a case and a question. It can narrow the scope and the budget, but it cannot
widen them: `admission` derives the permissions from the case. The report holds digests and
finding IDs only, so a raster, a value or a credential has no field to travel in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.planning.vocab import ResearchIntent
from earthlab.workflow.contracts import SHA256, WorkflowStatus

REQUEST_MEDIA_TYPE = "application/vnd.earthlab.engineer-task.v1+json"
REPORT_MEDIA_TYPE = "application/vnd.earthlab.engineer-report.v1+json"
REFUSAL_MEDIA_TYPE = "application/vnd.earthlab.engineer-refusal.v1+json"

REQUEST_ID = r"^[a-z0-9][a-z0-9._-]{0,63}$"  # short enough for the ".ge" engineer suffix
TRACE_ID = r"^[0-9a-f]{32}$"  # the W3C trace-id form

RefusalCode = Literal[
    "unknown_case",
    "tool_out_of_scope",
    "dataset_out_of_scope",
    "budget_above_limit",
    "brief_invalid",
]


class RequestedBudget(Strict):
    """Lower limits for one task. A value above the server's limit is refused."""

    max_turns: int | None = Field(default=None, gt=0)
    max_tool_calls: int | None = Field(default=None, gt=0)
    max_seconds: float | None = Field(default=None, gt=0)
    max_usd: float | None = Field(default=None, ge=0)


class EngineerTaskRequestV1(Strict):
    """What a peer may ask for. The A2A task ID is the server's; `request_id` is the peer's
    idempotency key, because the protocol does not let a client choose a task ID."""

    schema_version: Literal["1"] = "1"
    request_id: str = Field(pattern=REQUEST_ID)
    trace_id: str = Field(pattern=TRACE_ID)
    question: str = Field(min_length=5, max_length=400)
    case_id: str = Field(max_length=80)
    intent: ResearchIntent
    target_quantity: str | None = Field(default=None, max_length=80)
    period_start: datetime | None = None
    period_end: datetime | None = None
    constraints: tuple[str, ...] = Field(default=(), max_length=6)
    requested_tools: tuple[str, ...] = Field(default=(), max_length=32)
    requested_datasets: tuple[str, ...] = Field(default=(), max_length=32)
    budget: RequestedBudget = RequestedBudget()


class RefusalV1(Strict):
    """Why admission refused a task. The engineer did not run."""

    schema_version: Literal["1"] = "1"
    code: RefusalCode
    detail: str = Field(max_length=500)


class EngineerRunReportV1(Strict):
    """The final artifact: the run as the controller saw it, from the run record."""

    schema_version: Literal["1"] = "1"
    status_label: Literal["experimental"] = "experimental"
    a2a_task_id: str
    context_id: str
    request_id: str = Field(pattern=REQUEST_ID)
    trace_id: str = Field(pattern=TRACE_ID)
    request_sha256: str = Field(pattern=SHA256)
    engineering_task_id: str
    engineering_task_sha256: str = Field(pattern=SHA256)
    status: WorkflowStatus
    verified_finding_ids: tuple[str, ...]
    limitation_reasons: tuple[str, ...]
    plan_sha256: tuple[str, ...]
    critic_verdicts: tuple[str, ...]
    source_sha256: tuple[str, ...]
    result_sha256: str = Field(pattern=SHA256)
    trace_head_sha256: str = Field(pattern=SHA256)
    provider: str
    model: str
    served_model: str | None
    elapsed_ms: int = Field(ge=0)
