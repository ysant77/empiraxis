"""EventV1: the safe-to-display event contract. Roles come from earthlab.roles.

Implemented and experimental roles can appear in recorded artifacts. Planned roles are
listed so that a view can show them as planned; the adapter never emits them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from earthlab.roles import (
    EXPERIMENTAL_ROLES,
    IMPLEMENTED_ROLES,
    MODEL_AGENT_ROLES,
    PLANNED_ROLES,
    ROLE_LABELS,
    RoleId,
    is_model_agent,
)

__all__ = [
    "EXPERIMENTAL_ROLES",
    "IMPLEMENTED_ROLES",
    "MODEL_AGENT_ROLES",
    "PLANNED_ROLES",
    "ROLE_LABELS",
    "VISIBILITY_ORDER",
    "ActorRole",
    "EventStatus",
    "EventType",
    "EventV1",
    "Visibility",
    "is_model_agent",
]

ActorRole = RoleId
EventType = Literal[
    "task_proposed",
    "run_started",
    "source_pinned",
    "safety_checked",
    "tool_requested",
    "tool_completed",
    "claim_verified",
    "answer_submitted",
    "revision_proposed",
    "plan_submitted",
    "plan_reviewed",
    "approval_requested",
    "approval_resolved",
    "error",
    "run_completed",
    "role_invocation_started",
    "role_invocation_finished",
    "brief_validated",
    "task_handoff_created",
    "verified_result_delivered",
    "pm_report_issued",
]
EventStatus = Literal[
    "proposed", "pending", "approved", "rejected", "executed", "blocked", "failed", "completed"
]


class Visibility(StrEnum):
    """Who may see an event. Each level also sees every level before it."""

    PUBLIC_DEMO = "public_demo"
    AUTHENTICATED_REVIEWER = "authenticated_reviewer"
    INTERNAL = "internal"


VISIBILITY_ORDER = (Visibility.PUBLIC_DEMO, Visibility.AUTHENTICATED_REVIEWER, Visibility.INTERNAL)


class EventV1(BaseModel):
    """One recorded action, summarised. Never holds a raw prompt, hidden reasoning or a key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    run_id: str
    trace_id: str
    parent_event_id: str | None = None
    timestamp_utc: str
    actor_role: ActorRole
    receiver_role: ActorRole | None = None
    event_type: EventType
    status: EventStatus
    task_id: str | None = None
    plan_revision: int | None = None  # same type as InvestigationPlan.plan_revision
    message_summary: str
    evidence_refs: list[str] = []
    source_trace_ref: str | None = None
    elapsed_ms: int | None = None
    display_visibility: Visibility = Visibility.PUBLIC_DEMO
    schema_version: Literal["1"] = "1"
