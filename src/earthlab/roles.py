"""The one role list for plans, critic reports, trace events and the UI.

The orchestrator (the single Muse investigator) is a language-model role. The product
manager and geospatial engineer are experimental model roles: the workflow in
earthlab.workflow runs them, tested with a scripted client, with no live run recorded yet.
The verifier, safety gate, tools and runtime are code. Planned roles are listed so that
records stay compatible and a view can show them as planned; no code runs them.
"""

from __future__ import annotations

from typing import Literal

RoleId = Literal[
    "human_director",
    "product_manager",
    "orchestrator",
    "geospatial_engineer",
    "data_specialist",
    "ml_engineer",
    "implementor",
    "qa_reviewer",
    "scientific_critic",
    "verifier",
    "safety_gate",
    "tool",
    "system",
]

# Roles that recorded artifacts produce today. The scientific critic is deterministic code
# (earthlab.planning.critic), not a model.
IMPLEMENTED_ROLES: frozenset[RoleId] = frozenset(
    {
        "human_director",
        "orchestrator",
        "scientific_critic",
        "verifier",
        "safety_gate",
        "tool",
        "system",
    }
)
EXPERIMENTAL_ROLES: frozenset[RoleId] = frozenset(
    {"product_manager", "geospatial_engineer", "data_specialist", "ml_engineer"}
)
PLANNED_ROLES: frozenset[RoleId] = frozenset({"implementor", "qa_reviewer"})
MODEL_AGENT_ROLES: frozenset[RoleId] = frozenset(
    {"orchestrator", "product_manager", "geospatial_engineer", "data_specialist", "ml_engineer"}
)
# Roles that may write an investigation plan. Code components and the critic never do;
# the product manager only proposes a question.
PLAN_AUTHOR_ROLES: frozenset[RoleId] = frozenset(
    {"human_director", "orchestrator", "geospatial_engineer"}
)
ROLE_LABELS: dict[str, str] = {
    "human_director": "Human director",
    "product_manager": "Product manager (Meta model; structures the request, no tools)",
    "orchestrator": "Muse research orchestrator (investigator)",
    "geospatial_engineer": "Geospatial Lead (Muse; plan-reviewed investigator, delegates tickets)",
    "data_specialist": "Data specialist (one read-only tool on one ticket; code recomputes it)",
    "ml_engineer": "ML/DL engineer (runs approved templates only; never writes code)",
    "implementor": "Implementation worker (Meta or non-Meta model; proposes patches only)",
    "qa_reviewer": "Model reviewer (findings only; cannot override tests or the verifier)",
    "scientific_critic": "Scientific critic (deterministic plan rules, code, not a model)",
    "verifier": "Deterministic verifier (code, not a model)",
    "safety_gate": "Safety gate (scope rules and optional Llama Guard)",
    "tool": "Scientific tool (code, not a model)",
    "system": "Runtime",
}


def is_model_agent(role: str) -> bool:
    """True only for a role that a language model plays. Tools and the verifier never are."""
    return role in MODEL_AGENT_ROLES
