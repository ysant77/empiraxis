"""Role-to-model bindings, loaded from config/roles/bindings.yaml and checked before use.

A role is not a model and a model is not a provider. Supervising roles (product manager,
orchestrator, geospatial engineer, model reviewer) are bound to Meta families only; an
implementor may be any open-weight family. A candidate serves a role only when it is
enabled, lists the role under `roles`, has a checked licence and has passed preflight.
There is no fallback: `bind` names one candidate or fails.

Four facts are kept apart, because each fails for a different reason:

- implementation: whether the role's code is implemented, experimental or planned;
- provider: whether the candidate's endpoint is configured and enabled in providers.yaml;
- preflight: whether a recorded preflight passed;
- licence: whether a human checked the model licence.

`bind_runtime` checks all four plus the identity of the client that will serve the role.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import Field, model_validator

from earthlab.contracts import Strict
from earthlab.implement.contracts import ModelFamily
from earthlab.llm.providers import ProviderConfig

BindableRole = Literal[
    "product_manager",
    "orchestrator",
    "geospatial_engineer",
    "data_specialist",
    "ml_engineer",
    "implementor",
    "qa_reviewer",
]
META_FAMILIES: frozenset[str] = frozenset({"meta-muse", "meta-llama"})
SUPERVISING_ROLES: frozenset[str] = frozenset(
    {"product_manager", "orchestrator", "geospatial_engineer", "qa_reviewer"}
)
Check = Literal["pass", "fail", "text_only", "not_run"]
Implementation = Literal["implemented", "experimental", "planned"]


class BindingRefused(PermissionError):
    """A role cannot be served by this candidate or this client now."""


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
    status: Implementation


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

    def status(
        self, role: BindableRole, candidate_id: str, providers: Mapping[str, ProviderConfig]
    ) -> BindingStatus:
        c = self.candidate(candidate_id)
        endpoint = providers.get(c.provider_id or "")
        provider: Literal["available", "disabled", "not_configured"] = (
            "not_configured"
            if endpoint is None
            else "available"
            if endpoint.enabled
            else "disabled"
        )
        preflight: Literal["passed", "failed", "not_run"] = (
            "not_run" if c.preflight is None else "passed" if c.preflight.passed() else "failed"
        )
        return BindingStatus(
            role=role,
            candidate_id=candidate_id,
            listed=role in c.roles,
            implementation=self.roles[role].status,
            provider=provider,
            preflight=preflight,
            licence="approved" if c.license_checked else "not_checked",
            approved_for_use=c.enabled,
        )

    def bind_runtime(
        self,
        role: BindableRole,
        candidate_id: str,
        client: ProviderConfig,
        providers: Mapping[str, ProviderConfig],
        *,
        allow_experimental: bool = False,
    ) -> RoleBinding:
        """Bind the role to the candidate served by this client, or raise BindingRefused."""
        state = self.status(role, candidate_id, providers)
        problems = state.blockers(allow_experimental)
        c = self.candidate(candidate_id)
        if client.name != c.provider_id:
            problems.append(f"client provider {client.name} is not {c.provider_id}")
        if client.model != c.model_id:
            problems.append(f"client model {client.model} is not {c.model_id}")
        if problems:
            raise BindingRefused(f"{role} <- {candidate_id}: " + "; ".join(problems))
        return RoleBinding(
            role=role,
            candidate_id=candidate_id,
            family=c.family,
            model_id=c.model_id,
            provider_id=client.name,
            implementation=state.implementation,
        )


class BindingStatus(Strict):
    role: BindableRole
    candidate_id: str
    listed: bool
    implementation: Implementation
    provider: Literal["available", "disabled", "not_configured"]
    preflight: Literal["passed", "failed", "not_run"]
    licence: Literal["approved", "not_checked"]
    approved_for_use: bool

    def blockers(self, allow_experimental: bool = False) -> list[str]:
        """Every reason the role cannot run on this candidate now; empty when it can."""
        found = [] if self.listed else [f"{self.candidate_id} is not listed for {self.role}"]
        if self.implementation == "planned":
            found.append(f"{self.role} is planned, not implemented")
        if self.implementation == "experimental" and not allow_experimental:
            found.append(f"{self.role} is experimental; it needs an explicit opt-in")
        if self.provider != "available":
            found.append(f"provider is {self.provider.replace('_', ' ')}")
        if self.preflight != "passed":
            found.append(f"preflight {self.preflight.replace('_', ' ')}")
        if self.licence != "approved":
            found.append("licence not checked")
        if not self.approved_for_use:
            found.append("candidate not approved for use")
        return found


class RoleBinding(Strict):
    """The resolved binding a run records: which candidate serves which role, and how."""

    role: BindableRole
    candidate_id: str
    family: ModelFamily
    model_id: str
    provider_id: str
    implementation: Implementation


def load_bindings(path: Path) -> Bindings:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Bindings.model_validate(raw)
