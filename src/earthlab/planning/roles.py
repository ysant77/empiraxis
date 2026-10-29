"""Display visibility and task links for plans and critic reports.

The role list lives in earthlab.roles, shared with the trace events and the UI.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from earthlab.contracts import Strict
from earthlab.roles import PLAN_AUTHOR_ROLES, RoleId

__all__ = ["PLAN_AUTHOR_ROLES", "RoleId", "TaskMeta", "Visibility"]

TASK_ID = r"^[a-z0-9][a-z0-9._-]*$"

Visibility = Literal["public_demo", "authenticated_reviewer", "internal"]


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
