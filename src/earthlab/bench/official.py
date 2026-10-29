"""The official held-out run: every setting comes from the frozen protocol, the scenario
file must match its lock, and the run stops before the first question if anything drifts.
A check-only call does all the checks and runs no question.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from earthlab.bench.heldout import HeldoutError, load_lock, scenario_file_record
from earthlab.bench.protocol import Protocol, check_protocol, mark_official, official_root
from earthlab.bench.runner import check_official, run_bench, run_metadata
from earthlab.bench.scenarios import ScenarioScore, load_scenarios
from earthlab.llm.client import ChatClient
from earthlab.runtime import Workspace, new_run_dir
from earthlab.safety.llama_guard import LlamaGuard


class OfficialSetup:
    """What an official run needs, built by the caller from the protocol."""

    def __init__(
        self,
        repo: Path,
        protocol: Protocol,
        scenarios: Path,
        workspace: Workspace,
        client: ChatClient | None,
        guard: LlamaGuard | None,
    ):
        self.repo, self.protocol, self.workspace = repo, protocol, workspace
        self.client, self.guard = client, guard
        self.scenario_path = scenarios
        self.scenarios = load_scenarios(scenarios)
        lock = load_lock(repo / protocol.lock)
        self.scenario_file = scenario_file_record(scenarios, self.scenarios, lock)

    def metadata(self) -> dict[str, Any]:
        p = self.protocol
        return run_metadata(
            self.repo,
            self.workspace,
            self.client,
            p.budget,
            self.scenario_file,
            p.reasoning_prompt,
            self.guard,
        ) | {"arms": list(p.arms), "repeats": p.repeats}


def check_only(setup: OfficialSetup) -> dict[str, Any]:
    """All checks of an official run; no question runs and no folder is made."""
    meta = setup.metadata()
    check_official(meta)
    check_protocol(setup.protocol, meta, setup.repo)
    return meta


def run_official(
    setup: OfficialSetup,
    rerun_reason: str | None,
    on_score: Callable[[ScenarioScore], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    p = setup.protocol
    out_dir = new_run_dir(official_root(setup.repo, p, rerun_reason))

    def start(meta: dict[str, Any]) -> None:
        check_protocol(p, meta, setup.repo)
        mark_official(out_dir, p, rerun_reason)

    try:
        summary = run_bench(
            setup.scenarios,
            list(p.arms),
            setup.workspace,
            out_dir,
            repo=setup.repo,
            client=setup.client,
            guard=setup.guard,
            budget=p.budget,
            repeats=p.repeats,
            on_score=on_score,
            scenario_file=setup.scenario_file,
            reasoning=p.reasoning_prompt,
            before_rows=start,
        )
    except HeldoutError:
        if not any(out_dir.iterdir()):
            out_dir.rmdir()  # a refused start leaves no folder behind
        raise
    return out_dir, summary
