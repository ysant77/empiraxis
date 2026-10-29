"""The one role list for plans, critic reports, trace events and the UI.

Only the orchestrator (the Muse investigator) is played by a language model. The verifier,
safety gate, tools and runtime are code. Planned roles are listed so that records stay
compatible and a view can show them as planned; no code runs them as separate agents.
"""

from __future__ import annotations

from typing import Literal

RoleId = Literal[
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

# Roles that recorded artifacts produce today.
IMPLEMENTED_ROLES: frozenset[RoleId] = frozenset(
    {"human_director", "orchestrator", "verifier", "safety_gate", "tool", "system"}
)
PLANNED_ROLES: frozenset[RoleId] = frozenset(
    {"product_manager", "geospatial_engineer", "scientific_critic"}
)
MODEL_AGENT_ROLES: frozenset[RoleId] = frozenset({"orchestrator"})
# Roles that may write an investigation plan. Code components and the critic never do;
# the product manager only proposes a question.
PLAN_AUTHOR_ROLES: frozenset[RoleId] = frozenset(
    {"human_director", "orchestrator", "geospatial_engineer"}
)
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
