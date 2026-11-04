"""Model identity of each council role: which checkpoint serves which seat.

The registry in `config/benchmark/checkpoints.yaml` maps a provider to one GGUF file and its
SHA-256. A run writes one `role_binding` record per model seat and one `council_formed`
record, before the first model call. A council is heterogeneous only when two or more seats
are served by different checkpoint digests. Different prompts to one checkpoint do not count.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from earthlab.contracts import Strict
from earthlab.llm.client import ChatClient
from earthlab.trace import RunTrace

SHA256 = r"^[0-9a-f]{64}$"
SeatKind = Literal["investigator", "supervisor", "specialist", "critic"]
SEAT_KIND: dict[str, SeatKind] = {
    "product_manager": "supervisor", "geospatial_engineer": "investigator",
    "data_specialist": "specialist", "ml_engineer": "specialist", "method_critic": "critic",
}  # fmt: skip


class CheckpointV1(Strict):
    provider: str
    family: str
    file: str
    sha256: str = Field(pattern=SHA256)
    size_bytes: int = Field(gt=0)
    quantization: str
    licence: str
    source: str
    serving_note: str = ""


class RoleBindingV1(Strict):
    """What a trace shows for one seat. It holds no prompt, no key and no model text."""

    role: str
    seat: SeatKind
    provider: str
    served_alias: str
    family: str
    logical_model: str
    checkpoint_file: str
    checkpoint_sha256: str = Field(pattern=SHA256)
    size_bytes: int
    quantization: str
    licence: str
    source: str
    client_kind: str


def load_registry(path: Path) -> dict[str, CheckpointV1]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = [CheckpointV1.model_validate(c) for c in raw.get("checkpoints", [])]
    return {c.provider: c for c in items}


def file_sha256(path: Path) -> str:
    """Stream the file; GGUF files are many gigabytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 24), b""):
            digest.update(block)
    return digest.hexdigest()


def bindings_of(
    clients: Mapping[str, ChatClient], registry: Mapping[str, CheckpointV1]
) -> list[RoleBindingV1]:
    """One binding per seat. A seat whose provider has no checkpoint entry is an error."""
    found: list[RoleBindingV1] = []
    for role in sorted(clients, key=list(SEAT_KIND).index):
        cfg = clients[role].config
        ckpt = registry.get(cfg.name)
        if ckpt is None:
            raise KeyError(f"{role}: provider {cfg.name} has no checkpoint entry")
        kind = type(clients[role]).__name__
        found.append(
            RoleBindingV1(
                role=role, seat=SEAT_KIND[role], provider=cfg.name, served_alias=cfg.model,
                family=ckpt.family, logical_model=cfg.logical_model, checkpoint_file=ckpt.file,
                checkpoint_sha256=ckpt.sha256, size_bytes=ckpt.size_bytes,
                quantization=ckpt.quantization, licence=ckpt.licence, source=ckpt.source,
                client_kind=kind,
            )
        )  # fmt: skip
    return found


def council_summary(bound: list[RoleBindingV1]) -> dict[str, Any]:
    """The facts a reader needs: how many checkpoints, which seats share one."""
    by_sha: dict[str, list[str]] = {}
    for b in bound:
        by_sha.setdefault(b.checkpoint_sha256, []).append(b.role)
    families = sorted({b.family for b in bound})
    return {
        "seats": len(bound),
        "distinct_checkpoints": len(by_sha),
        "heterogeneous": len(by_sha) > 1,
        "families": families,
        "seats_per_checkpoint": {sha[:12]: roles for sha, roles in by_sha.items()},
    }


def record_council(trace: RunTrace, bound: list[RoleBindingV1]) -> dict[str, Any]:
    """Write the bindings and the summary to the trace, before the first model call."""
    for b in bound:
        trace.append("role_binding", "runtime", **b.model_dump(mode="json"))
    summary = council_summary(bound)
    trace.append("council_formed", "runtime", **summary)
    return summary
