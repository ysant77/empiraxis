"""Arm configuration: which provider serves which role, and which prompt variant is used.

An arm names a provider for the PM, the Lead and the specialists. The names point at
`config/providers.yaml`. A role keeps the model that the arm names. There is no silent
substitution: a provider that fails a binding gate stops the arm before any run.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Literal, Self

from pydantic import model_validator

from earthlab.contracts import Strict
from earthlab.harness.engine import DATA, LEAD, ML, PM, Arm
from earthlab.implement.bindings import BindableRole, Bindings
from earthlab.llm.client import ChatClient, build_client
from earthlab.llm.providers import ProviderConfig

MUSE_PROVIDER = "local-glimmer"
ROLE_NAMES: dict[str, tuple[str, ...]] = {"pm": (PM,), "lead": (LEAD,), "specialist": (DATA, ML)}


class ArmSpec(Strict):
    """One arm of the matrix. Role fields hold provider names."""

    arm_id: str
    arm: Arm
    prompt_variant: str = "baseline"
    pm: str | None = None
    lead: str | None = None
    specialist: str | None = None
    muse_roles: tuple[Literal["pm", "lead", "specialist"], ...] = ()
    ranked: bool = True
    lead_gate_waived: bool = False
    note: str = ""

    @model_validator(mode="after")
    def _roles_fit_the_arm(self) -> Self:
        named = {k for k in ROLE_NAMES if getattr(self, k) is not None}
        need = {"fixed": set(), "single": {"lead"}, "team": {"pm", "lead", "specialist"}}[self.arm]
        if named != need:
            raise ValueError(f"{self.arm_id}: the {self.arm} arm names roles {sorted(need)}")
        if self.lead_gate_waived and (self.ranked or self.arm != "single"):
            raise ValueError(f"{self.arm_id}: a waived Lead gate needs a single, unranked arm")
        if not set(self.muse_roles) <= named:
            raise ValueError(f"{self.arm_id}: a Muse role must be a named role")
        return self

    def providers(self) -> dict[str, str]:
        """Harness role name to provider name."""
        return {
            r: getattr(self, k)
            for k, roles in ROLE_NAMES.items()
            for r in roles
            if getattr(self, k)
        }

    @property
    def block(self) -> str:
        """The model servers this arm needs: `none`, `muse`, or `muse+<small providers>`."""
        names = set(self.providers().values())
        small = sorted(n for n in names if n != MUSE_PROVIDER)
        if not names:
            return "none"
        if MUSE_PROVIDER not in names:
            return "+".join(small)
        return "+".join(["muse", *small])


def gate_blockers(
    spec: ArmSpec, bindings: Bindings, providers: Mapping[str, ProviderConfig]
) -> list[str]:
    """Every reason the arm cannot run now. Empty means every role passes its gate."""
    found: list[str] = []
    for key in spec.muse_roles:
        cfg = providers.get(getattr(spec, key))
        if cfg is None or not cfg.logical_model.startswith("muse-"):
            found.append(f"{spec.arm_id}: the {key} role must be a Muse model")
    for role, name in spec.providers().items():
        cfg = providers.get(name)
        owner = next((c for c in bindings.candidates if c.provider_id == name), None)
        if cfg is None or owner is None:
            found.append(f"{spec.arm_id}/{role}: provider {name} has no candidate")
            continue
        # A waived Lead gate tests the model in the specialist seat's gate. The arm is unranked.
        seat = "data_specialist" if spec.lead_gate_waived and role == LEAD else role_for(role)
        status = bindings.status(seat, owner.candidate_id, providers)
        found += [f"{spec.arm_id}/{role}/{owner.candidate_id}: {b}" for b in
                  status.blockers(allow_experimental=True)]  # fmt: skip
    return found


def role_for(role: str) -> BindableRole:
    known: dict[str, BindableRole] = {
        PM: "product_manager", LEAD: "geospatial_engineer", DATA: "data_specialist",
        ML: "ml_engineer",
    }  # fmt: skip
    return known[role]


def build_role_clients(
    spec: ArmSpec, providers: Mapping[str, ProviderConfig],
    build: Callable[[ProviderConfig], ChatClient] = build_client,
) -> tuple[ChatClient | None, dict[str, ChatClient]]:  # fmt: skip
    """The default client (the Lead's) and one client per role. One client per provider."""
    made: dict[str, ChatClient] = {}
    per_role: dict[str, ChatClient] = {}
    for role, name in spec.providers().items():
        if name not in made:
            made[name] = build(providers[name])
        per_role[role] = made[name]
    return per_role.get(LEAD), per_role
