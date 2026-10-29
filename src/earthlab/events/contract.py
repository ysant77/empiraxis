"""EventV1: the safe-to-display event contract, and the role registry it depends on.

Only roles that a recorded artifact can produce are implemented. Planned roles are listed
so that a view can show them as planned; the adapter never emits them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

ActorRole = Literal[
    "human_director",
    "product_manager",
    "orchestrator",
    "geospatial_engineer",
    "scientific_critic",
    "verifier",
    "safety_gate",
    "tool",
    "system",
]
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
    "error",
    "run_completed",
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

# Roles that recorded artifacts produce today. The Muse investigator is the one model agent.
IMPLEMENTED_ROLES: frozenset[str] = frozenset(
    {"human_director", "orchestrator", "verifier", "safety_gate", "tool", "system"}
)
PLANNED_ROLES: frozenset[str] = frozenset(
    {"product_manager", "geospatial_engineer", "scientific_critic"}
)
MODEL_AGENT_ROLES: frozenset[str] = frozenset({"orchestrator"})
ROLE_LABELS: dict[str, str] = {
    "human_director": "Human director",
    "product_manager": "Product manager (research concierge)",
    "orchestrator": "Muse research orchestrator (investigator)",
    "geospatial_engineer": "Geospatial engineer",
    "scientific_critic": "Scientific critic",
    "verifier": "Deterministic verifier (code, not a model)",
    "safety_gate": "Safety gate (scope rules and optional Llama Guard)",
    "tool": "Scientific tool (code, not a model)",
    "system": "Runtime",
}


def is_model_agent(role: str) -> bool:
    """True only for a role that a language model plays. Tools and the verifier never are."""
    return role in MODEL_AGENT_ROLES


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
    plan_revision: str | None = None
    message_summary: str
    evidence_refs: list[str] = []
    source_trace_ref: str | None = None
    elapsed_ms: int | None = None
    display_visibility: Visibility = Visibility.PUBLIC_DEMO
    schema_version: Literal["1"] = "1"
