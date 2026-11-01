"""Run one stage of the benchmark matrix, one run at a time, and write a manifest.

The runner starts no model server. The operator starts the server for one block, and the
runner runs only the planned runs of that block. Before the first run it checks the commit
pin and the binding gate of every arm. A run that already has a manifest row is skipped.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from earthlab.digest import file_digest
from earthlab.harness.arms import ArmSpec, build_role_clients, gate_blockers
from earthlab.harness.matrix import WINNER, MatrixPlan, PlannedRun, expand, run_minutes
from earthlab.harness.scenarios import run_scenario
from earthlab.harness.variants import PromptVariant, VariantFile
from earthlab.implement.bindings import Bindings
from earthlab.llm.client import ChatClient, build_client
from earthlab.llm.providers import ProviderConfig
from earthlab.runtime import new_run_dir

MAX_CONSECUTIVE_FAILURES = 2
OK_STATES = ("awaiting_human", "refused", "abstained")
RunOne = Callable[..., dict[str, Any]]


class Refused(Exception):
    """The stage cannot start. The message lists every reason."""


def _git(repo: Path, *args: str) -> str:
    """Fixed git arguments only; no user input reaches the command line."""
    git = shutil.which("git")
    if git is None:
        raise Refused("git is not installed")
    done = subprocess.run([git, "-C", str(repo), *args], capture_output=True, text=True, check=True)  # noqa: S603
    return done.stdout.strip()


def git_state(root: Path) -> tuple[str, bool]:
    """The HEAD commit and whether the work tree has uncommitted changes."""
    return _git(root, "rev-parse", "HEAD"), bool(_git(root, "status", "--porcelain"))


def pin_problems(expected: str, head: str, dirty: bool) -> list[str]:
    found = []
    if len(expected) < 12 or not head.startswith(expected):
        found.append(f"HEAD {head[:12]} is not the pinned commit {expected[:12]}")
    if dirty:
        found.append("the work tree has uncommitted changes")
    return found


def variant_for(spec: ArmSpec, variants: VariantFile, winner: str | None) -> PromptVariant:
    name = spec.prompt_variant
    if name == WINNER:
        if winner is None:
            raise Refused(f"{spec.arm_id}: this arm needs --winner")
        name = winner
    return variants.get(name)


def preflight(
    plan: MatrixPlan, runs: list[PlannedRun], variants: VariantFile, winner: str | None,
    bindings: Bindings, providers: Mapping[str, ProviderConfig],
) -> None:  # fmt: skip
    """Raise Refused with every reason, before any run starts."""
    problems: list[str] = []
    for arm_id in sorted({r.arm_id for r in runs}):
        spec = plan.arm(arm_id)
        problems += gate_blockers(spec, bindings, providers)
        try:
            variant_for(spec, variants, winner)
        except (Refused, KeyError) as exc:
            problems.append(str(exc))
    if problems:
        raise Refused("; ".join(problems))


def _key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (row.get("stage"), row.get("repeat"), row.get("scenario"), row.get("arm_id"))


def done_keys(manifest: Path) -> set[tuple[Any, ...]]:
    if not manifest.is_file():
        return set()
    rows = (json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines())
    return {_key(r) for r in rows if "arm_id" in r}


def append(manifest: Path, row: dict[str, Any]) -> None:
    with manifest.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, default=str) + "\n")


def one_run(
    spec: ArmSpec, run: PlannedRun, variant: PromptVariant, providers: Mapping[str, ProviderConfig],
    runs_dir: Path, run_one: RunOne, build: Callable[[ProviderConfig], ChatClient],
) -> dict[str, Any]:  # fmt: skip
    """One run and its manifest row. A crash becomes a row, not an exception."""
    run_dir, began = new_run_dir(runs_dir), time.perf_counter()
    row: dict[str, Any] = {
        "stage": run.stage, "repeat": run.repeat, "order": run.order, "scenario": run.scenario,
        "arm": spec.arm, "arm_id": spec.arm_id, "prompt_variant": variant.id,
        "block": run.block, "models": spec.providers(), "run": str(run_dir),
    }  # fmt: skip
    try:
        client, per_role = build_role_clients(spec, providers, build)
        done = run_one(
            run.scenario, spec.arm, run_dir, client, role_clients=per_role, variant=variant
        )
        row |= {
            "status": done["status"],
            "err": "",
            "exit": 0 if done["status"] in OK_STATES else 2,
        }
    except Exception as exc:  # a crash must not end the stage; it is recorded and counted
        row |= {"status": "crashed", "err": f"{type(exc).__name__}: {str(exc)[:200]}", "exit": 2}
    row["wall"] = round(time.perf_counter() - began, 1)
    return row


def run_stage(
    plan: MatrixPlan, stage_id: str, block: str, *, variants: VariantFile,
    providers: Mapping[str, ProviderConfig], bindings: Bindings, pin: str, repo: Path,
    out_dir: Path, winner: str | None = None, minutes_left: float | None = None,
    run_one: RunOne = run_scenario, build: Callable[[ProviderConfig], ChatClient] = build_client,
    head_of: Callable[[Path], tuple[str, bool]] = git_state,
) -> list[dict[str, Any]]:  # fmt: skip
    """Run the planned runs of one block. Returns the rows it wrote."""
    head, dirty = head_of(repo)
    if problems := pin_problems(pin, head, dirty):
        raise Refused("; ".join(problems))
    todo = [r for r in expand(plan, stage_id) if r.block == block]
    preflight(plan, todo, variants, winner, bindings, providers)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest, seen = out_dir / "manifest.jsonl", done_keys(out_dir / "manifest.jsonl")
    if not manifest.is_file():
        digest = file_digest(repo / "config" / "benchmark" / "matrix.yaml")
        append(manifest, {"header": plan.matrix_id, "commit": head, "matrix_sha256": digest})
    rows: list[dict[str, Any]] = []
    for run in (r for r in todo if _key(r.model_dump()) not in seen):
        need = run_minutes(plan, run)
        if minutes_left is not None and need > minutes_left:
            append(manifest, {"stopped": "time budget", "next": run.model_dump()})
            break
        spec = plan.arm(run.arm_id)
        row = one_run(spec, run, variant_for(spec, variants, winner), providers, out_dir / "runs",
                      run_one, build) | {"commit": head}  # fmt: skip
        append(manifest, row)
        rows.append(row)
        minutes_left = None if minutes_left is None else minutes_left - row["wall"] / 60
        if _failing(rows):
            append(manifest, {"stopped": f"{MAX_CONSECUTIVE_FAILURES} failures in a row"})
            break
    return rows


def _failing(rows: list[dict[str, Any]]) -> bool:
    tail = rows[-MAX_CONSECUTIVE_FAILURES:]
    return len(tail) == MAX_CONSECUTIVE_FAILURES and all(r["exit"] != 0 for r in tail)
