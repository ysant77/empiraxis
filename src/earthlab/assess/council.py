"""Council configuration: which checkpoint serves each role, and how each role samples.

A role has exactly one provider. The council never substitutes a provider when a role fails.
Bindings are written to the trace before the first model call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from earthlab.assess.llm import Sampling, StructuredClient
from earthlab.assess.serving import Server
from earthlab.contracts import Strict
from earthlab.harness.identity import CheckpointV1
from earthlab.trace import RunTrace

ROLES = ("data_specialist", "ml_engineer", "lead", "critic", "rebuttal", "pm")
SEAT = {
    "data_specialist": "specialist",
    "ml_engineer": "specialist",
    "lead": "investigator",
    "critic": "critic",
    "rebuttal": "investigator",
    "pm": "supervisor",
}


class ArmV1(Strict):
    name: str
    roles: dict[str, str]  # role -> provider


class CouncilSpecV1(Strict):
    protocol: str
    sampling: Sampling
    template_kwargs: dict[str, dict[str, Any]]  # provider -> chat template arguments
    main_providers: list[str]
    arms: dict[str, dict[str, str]]


def load_spec(path: Path) -> CouncilSpecV1:
    spec = CouncilSpecV1.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    for name, roles in spec.arms.items():
        unknown = set(roles) - set(ROLES)
        if unknown:
            raise ValueError(f"arm {name}: unknown roles {sorted(unknown)}")
        if "critic" in roles and "rebuttal" not in roles:
            raise ValueError(f"arm {name}: a critic needs a rebuttal role")
    return spec


def arm_of(spec: CouncilSpecV1, name: str, **overrides: str) -> ArmV1:
    """Overrides replace a role's provider, for example a critic chosen by the critic test."""
    roles = {**spec.arms[name], **overrides}
    return ArmV1(name=name, roles=roles)


class Council:
    def __init__(
        self,
        spec: CouncilSpecV1,
        arm: ArmV1,
        clients: dict[str, StructuredClient],
        registry: dict[str, CheckpointV1],
        side: Server | None = None,
    ):
        missing = set(arm.roles.values()) - set(clients)
        if missing:
            raise KeyError(f"no client for providers {sorted(missing)}")
        self.spec, self.arm, self.clients = spec, arm, clients
        self.registry, self.side = registry, side

    def sampling(self, role: str) -> Sampling:
        provider = self.arm.roles[role]
        kwargs = self.spec.template_kwargs.get(provider, {})
        return self.spec.sampling.model_copy(update={"template_kwargs": kwargs})

    def sampling_table(self) -> dict[str, Any]:
        return {r: self.sampling(r).model_dump(mode="json") for r in self.arm.roles}

    def client(self, role: str) -> tuple[StructuredClient, dict[str, Any] | None]:
        provider = self.arm.roles[role]
        switch = None
        if provider not in self.spec.main_providers:
            if self.side is None:
                raise RuntimeError(f"{role}: {provider} needs the side server")
            seconds = self.side.ensure(provider)
            if seconds:
                switch = {"to": provider, "load_seconds": seconds}
        return self.clients[provider], switch

    def record_bindings(self, trace: RunTrace) -> dict[str, Any]:
        by_sha: dict[str, list[str]] = {}
        for role, provider in self.arm.roles.items():
            ckpt = self.registry.get(provider)
            if ckpt is None:
                raise KeyError(f"{role}: provider {provider} has no checkpoint entry")
            trace.append(
                "role_binding",
                "runtime",
                role=role,
                seat=SEAT[role],
                provider=provider,
                family=ckpt.family,
                checkpoint_file=ckpt.file,
                checkpoint_sha256=ckpt.sha256,
                quantization=ckpt.quantization,
                licence=ckpt.licence,
                source=ckpt.source,
            )
            by_sha.setdefault(ckpt.sha256, []).append(role)
        summary: dict[str, Any] = {
            "seats": len(self.arm.roles),
            "distinct_checkpoints": len(by_sha),
            "heterogeneous": len(by_sha) > 1,
            "seats_per_checkpoint": {k[:12]: v for k, v in by_sha.items()},
        }
        trace.append("council_formed", "runtime", **summary)
        return summary
