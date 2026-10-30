"""Role-to-model bindings, loaded from config/roles/bindings.yaml and checked before use.

A role is not a model and a model is not a provider. Supervising roles (product manager,
orchestrator, geospatial engineer, model reviewer) are bound to Meta families only; an
implementor may be any open-weight family. A candidate serves a role only when it is
enabled, lists the role under `roles`, has a checked licence and has passed preflight.
There is no fallback: `bind` names one candidate or fails.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import Field, model_validator

from earthlab.contracts import Strict
from earthlab.implement.contracts import ModelFamily

BindableRole = Literal[
    "product_manager", "orchestrator", "geospatial_engineer", "implementor", "qa_reviewer"
]
META_FAMILIES: frozenset[str] = frozenset({"meta-muse", "meta-llama"})
SUPERVISING_ROLES: frozenset[str] = frozenset(
    {"product_manager", "orchestrator", "geospatial_engineer", "qa_reviewer"}
)
Check = Literal["pass", "fail", "text_only", "not_run"]


class Preflight(Strict):
    checked_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    json_schema: Check
    tool_call: Check  # text_only: the model returns a typed patch, not tool calls
    served_model: str
    peak_memory_gb: float | None = None
    note: str = ""

    def passed(self) -> bool:
        return self.json_schema == "pass" and self.tool_call in ("pass", "text_only")


class RolePolicy(Strict):
    families: tuple[ModelFamily, ...] = Field(min_length=1)
    status: Literal["implemented", "planned"]


class Candidate(Strict):
    candidate_id: str = Field(pattern=r"^[a-z0-9-]+$")
    family: ModelFamily
    model_id: str
    provider_id: str | None = None
    roles: tuple[BindableRole, ...] = ()
    planned_roles: tuple[BindableRole, ...] = ()
    license: str
    license_checked: bool = False
    enabled: bool = False
    preflight: Preflight | None = None

    @model_validator(mode="after")
    def _ready(self) -> Self:
        if set(self.roles) & set(self.planned_roles):
            raise ValueError(f"{self.candidate_id}: a role is both bound and planned")
        if not self.enabled:
            if self.roles:
                raise ValueError(f"{self.candidate_id}: a disabled candidate serves no role")
            return self
        if not self.license_checked:
            raise ValueError(f"{self.candidate_id}: enabled before its licence was checked")
        if self.preflight is None or not self.preflight.passed():
            raise ValueError(f"{self.candidate_id}: enabled without a passed preflight")
        if self.provider_id is None:
            raise ValueError(f"{self.candidate_id}: enabled without a provider")
        return self


class Bindings(Strict):
    schema_version: Literal["1"]
    roles: dict[BindableRole, RolePolicy]
    candidates: tuple[Candidate, ...]

    @model_validator(mode="after")
    def _families(self) -> Self:
        ids = [c.candidate_id for c in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("candidate IDs must be unique")
        for role, policy in self.roles.items():
            if role in SUPERVISING_ROLES and not set(policy.families) <= META_FAMILIES:
                raise ValueError(f"{role} is a supervising role and takes Meta families only")
        for c in self.candidates:
            for role in (*c.roles, *c.planned_roles):
                if c.family not in self.roles[role].families:
                    raise ValueError(f"{c.candidate_id}: family {c.family} cannot serve {role}")
        return self

    def candidate(self, candidate_id: str) -> Candidate:
        for c in self.candidates:
            if c.candidate_id == candidate_id:
                return c
        raise KeyError(f"unknown candidate {candidate_id}")

    def bind(self, role: BindableRole, candidate_id: str) -> Candidate:
        """The named candidate for the role, or an error. Never a substitute."""
        c = self.candidate(candidate_id)
        if role not in c.roles:
            state = "planned for" if role in c.planned_roles else "not listed for"
            raise PermissionError(f"{candidate_id} is {state} {role}; it cannot serve it now")
        return c

    def ready(self, role: BindableRole) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if role in c.roles)


def load_bindings(path: Path) -> Bindings:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Bindings.model_validate(raw)
