"""Typed investigation plans and a deterministic plan critic.

This package is not wired into the agent loop, the runtime or the bench. It defines the
plan a model will later propose and the code that reviews it before a human approves it.
"""

from earthlab.planning.critic import plan_digest, review_plan
from earthlab.planning.plan import PLAN_SCHEMA_VERSION, InvestigationPlan, load_plan
from earthlab.planning.registry import Registry, candidates_from_case, load_registry
from earthlab.planning.report import CheckId, CriticReport, Finding

__all__ = [
    "PLAN_SCHEMA_VERSION",
    "CheckId",
    "CriticReport",
    "Finding",
    "InvestigationPlan",
    "Registry",
    "candidates_from_case",
    "load_plan",
    "load_registry",
    "plan_digest",
    "review_plan",
]
