"""Role identity, display visibility and task links for plans and critic reports.

The role list is a copy of the design contract (docs: role and event contract v1). The
event stream keeps the same list; a later change will merge the two into one module.

Implementation truth at this revision: only the orchestrator (the Muse investigator) is a
model-led actor. The verifier, tools and the deterministic critic are code. The product
manager, geospatial engineer and model critic roles are future-facing; a plan may name
them so that later records stay compatible, but no code runs them as separate agents.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from earthlab.contracts import Strict

TASK_ID = r"^[a-z0-9][a-z0-9._-]*$"

RoleId = Literal[
    "human_director",
    "product_manager",
    "orchestrator",
    "geospatial_engineer",
    "scientific_critic",
    "verifier",
    "tool",
    "system",
]
Visibility = Literal["public_demo", "authenticated_reviewer", "internal"]

# Roles that may write an investigation plan. Code components (verifier, tool, system)
# and the critic never author a plan; the product manager only proposes a question.
PLAN_AUTHOR_ROLES: frozenset[RoleId] = frozenset(
    {"human_director", "orchestrator", "geospatial_engineer"}
)


class TaskMeta(Strict):
    """Stable identity of one unit of work, so a director console can show real work.

    `parent_task_id` and `child_task_ids` are future-facing: no code delegates tasks yet.
    """

    task_id: str = Field(pattern=TASK_ID)
    role_id: RoleId
    visibility: Visibility = "internal"
    parent_task_id: str | None = Field(default=None, pattern=TASK_ID)
    child_task_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _no_self_link(self) -> Self:
        links = {self.parent_task_id, *self.child_task_ids}
        if self.task_id in links:
            raise ValueError("a task cannot be its own parent or child")
        if len(set(self.child_task_ids)) != len(self.child_task_ids):
            raise ValueError("child task IDs must be unique")
        if self.parent_task_id in self.child_task_ids:
            raise ValueError("a task cannot be both parent and child")
        return self
