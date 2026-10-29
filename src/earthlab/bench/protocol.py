"""The frozen measurement protocol for one held-out set. It fixes the arms, repeats, model,
safety model, reasoning setting, budget and the hashes of every file that can change a
score. An official run takes no tuning flags: it reads them all from the protocol, and it
refuses to start if the code, data or servers differ from what the protocol pins.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from earthlab.agent.budget import Budget
from earthlab.bench.heldout import HeldoutError
from earthlab.contracts import Strict
from earthlab.digest import file_digest

OFFICIAL_MARKER = "official_run.json"


class PlannerServerPin(Strict):
    model_path: str
    build_info: str
    n_ctx: int = Field(gt=0)
    sampling_defaults: dict[str, float | int]


class Protocol(Strict):
    protocol_id: str
    set_id: str
    lock: str
    lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_at: date
    arms: list[Literal["A", "B"]] = Field(min_length=1)
    repeats: int = Field(ge=1, le=10)
    provider: str
    guard: str
    reasoning_prompt: Literal["low", "medium", "high"]
    budget: Budget
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: dict[str, str] = Field(min_length=1)
    planner_server: PlannerServerPin
    guard_model_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    official_dir: str
    notes: list[str] = Field(default_factory=list)


def load_protocol(path: Path) -> Protocol:
    return Protocol.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _differ(name: str, pinned: Any, actual: Any) -> list[str]:
    return [] if pinned == actual else [f"{name}: protocol {pinned!r}, run {actual!r}"]


def _hash_drift(pinned: dict[str, str], actual: dict[str, str]) -> list[str]:
    names = sorted(set(pinned) | set(actual))
    return [
        f"config_sha256 {n}: protocol {pinned.get(n)}, run {actual.get(n)}"
        for n in names
        if pinned.get(n) != actual.get(n)
    ]


def _server_drift(protocol: Protocol, meta: dict[str, Any]) -> list[str]:
    planner = (meta.get("planner") or {}).get("server", {})
    pin = protocol.planner_server.model_dump()
    drift = [d for key, want in pin.items() for d in _differ(key, want, planner.get(key))]
    guard = meta.get("guard", {})
    digest = guard.get("server", {}).get("model_digest")
    drift += _differ("guard_model_digest", protocol.guard_model_digest, digest)
    return drift


def protocol_drift(protocol: Protocol, meta: dict[str, Any], repo: Path) -> list[str]:
    """Every difference between the protocol and this run; empty when the run matches."""
    drift = _differ("lock_sha256", protocol.lock_sha256, file_digest(repo / protocol.lock))
    drift += _differ("set_id", protocol.set_id, (meta.get("scenario_file") or {}).get("set_id"))
    drift += _differ("data_sha256", protocol.data_sha256, meta["data_sha256"])
    drift += _differ("budget", protocol.budget.model_dump(), meta["budget"])
    drift += _differ("reasoning_prompt", protocol.reasoning_prompt, meta["reasoning_prompt"])
    drift += _differ("arms", protocol.arms, meta.get("arms"))
    drift += _differ("repeats", protocol.repeats, meta.get("repeats"))
    drift += _hash_drift(protocol.config_sha256, meta["config_sha256"])
    if "B" not in protocol.arms:
        return drift  # arm A calls no model and no safety model
    drift += _differ("provider", protocol.provider, meta["provider"])
    return drift + _server_drift(protocol, meta)


def check_protocol(protocol: Protocol, meta: dict[str, Any], repo: Path) -> None:
    drift = protocol_drift(protocol, meta, repo)
    if drift:
        raise HeldoutError("the run does not match the frozen protocol:\n  " + "\n  ".join(drift))


def official_root(repo: Path, protocol: Protocol, rerun_reason: str | None) -> Path:
    """The official run folder. A second official run needs a stated reason."""
    root = repo / protocol.official_dir
    earlier = earlier_official_runs(root)
    if earlier and not (rerun_reason and rerun_reason.strip()):
        raise HeldoutError(
            f"an official run exists ({', '.join(earlier)}); a new one needs --rerun-reason"
        )
    return root


def earlier_official_runs(root: Path) -> list[str]:
    """Runs that passed the protocol check and started. A start refused by the check
    leaves no marker, so it does not count."""
    return sorted(p.parent.name for p in root.glob(f"*/{OFFICIAL_MARKER}"))


def mark_official(out_dir: Path, protocol: Protocol, rerun_reason: str | None) -> None:
    """Written after the protocol check passes and before the first question runs."""
    earlier = [r for r in earlier_official_runs(out_dir.parent) if r != out_dir.name]
    marker = {
        "protocol_id": protocol.protocol_id,
        "earlier_runs": earlier,
        "rerun_reason": rerun_reason if earlier else None,
    }
    (out_dir / OFFICIAL_MARKER).write_text(json.dumps(marker, indent=2), encoding="utf-8")
