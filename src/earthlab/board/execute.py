"""Run one requested investigation with the same options as the command line.

The worker calls this outside the UI process, so a page refresh cannot start or stop a run.
Python keeps all authority: the views submit a request and read the trace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from earthlab.agent.budget import Budget
from earthlab.board.store import RunSpec
from earthlab.llm.client import build_client
from earthlab.llm.providers import ProviderConfig, load_providers
from earthlab.llm.raw import RawCompletionClient
from earthlab.report.write import write_report
from earthlab.runtime import RunOptions, Workspace, investigate
from earthlab.safety.llama_guard import LlamaGuard
from earthlab.workflow.assign import repo_assignment
from earthlab.workflow.run import run_workflow


def build_guard(configs: dict[str, ProviderConfig], name: str) -> LlamaGuard | None:
    if name == "none":
        return None
    return LlamaGuard(RawCompletionClient(configs[name]), configs[name].logical_model)


def execute(
    spec: RunSpec, run_dir: Path, workspace: Workspace, providers: Path, data_dir: Path
) -> None:
    """One bounded run. The trace in run_dir records everything that happened."""
    configs = {n: c for n, c in load_providers(providers).items() if c.enabled}
    client = build_client(configs[spec.provider])
    settings: dict[str, Any] = {
        "budget": Budget(),
        "reasoning": spec.reasoning,
        "guard": build_guard(configs, spec.guard),
        "options": RunOptions(plan_review=True, render_fallback=True),
    }
    if spec.topology is None:
        investigate(spec.question, client, workspace, run_dir, **settings)
    else:
        orchestrator = client if spec.topology == "separate" else None
        run_workflow(
            spec.question, client, workspace, run_dir,
            assignment=repo_assignment(configs, client, topology=spec.topology),
            orchestrator_client=orchestrator, **settings,
        )  # fmt: skip
    if "rounds" in json.loads((run_dir / "result.json").read_text(encoding="utf-8")):
        write_report(run_dir, data_dir)
