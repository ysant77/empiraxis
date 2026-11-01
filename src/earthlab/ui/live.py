"""Live investigation controls for a local operator. Only operator mode calls run_live."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from earthlab.agent.budget import Budget
from earthlab.llm.client import ChatClient, build_client
from earthlab.llm.providers import ProviderConfig, load_providers
from earthlab.llm.raw import RawCompletionClient
from earthlab.runtime import RunOptions, investigate, new_run_dir
from earthlab.safety.llama_guard import LlamaGuard
from earthlab.ui import common
from earthlab.workflow.assign import repo_assignment
from earthlab.workflow.contracts import Topology
from earthlab.workflow.run import run_workflow

ROUTES: dict[str, Topology | None] = {
    "Direct Muse investigator (baseline)": None,
    "Muse PM, deterministic orchestrator, Muse engineer": "combined",
    "Muse PM, separate LLM orchestrator, Muse engineer": "separate",
}


def _listener(status: Any) -> Any:
    def listener(record: dict[str, Any]) -> None:
        data = record["data"]
        if record["event"] == "model_turn":
            names = ", ".join(c["name"] for c in data["tool_calls"]) or "final answer"
            status.write(f"Turn {data['turn']}: model chose **{names}**")
        elif record["event"] == "safety_check":
            verdict = "allowed" if data["allowed"] else f"blocked ({data['reason']})"
            status.write(f"Safety check on the {data['stage']}: {verdict}")
        elif record["event"] == "tool_result":
            status.write(f"`{data['name']}` -> {data['outcome']}")
        elif record["event"] == "brief_reviewed":
            status.write(f"Typed brief checked by Python: valid {data['valid']}, {data['route']}")
        elif record["event"] == "decision_reviewed":
            status.write(f"Orchestrator proposal checked by Python: valid {data['valid']}")
        elif record["event"] == "task_handoff":
            status.write(f"Task handed to the {data['receiver']}")
        elif record["event"] == "plan_reviewed":
            status.write(f"Plan critic (code): {data['verdict']}")

    return listener


def _guard(configs: dict[str, ProviderConfig], name: str) -> LlamaGuard | None:
    if name == "none":
        return None
    return LlamaGuard(RawCompletionClient(configs[name]), configs[name].logical_model)


def _run(
    question: str,
    topology: Topology | None,
    client: ChatClient,
    configs: dict[str, ProviderConfig],
    guard: LlamaGuard | None,
    reasoning: str,
    listener: Any,
) -> Path:
    """One bounded run on the same options as the command line. Python keeps all authority."""
    run_dir = new_run_dir(common.RUNS_DIR)
    settings: dict[str, Any] = {
        "budget": Budget(),
        "reasoning": reasoning,
        "listener": listener,
        "guard": guard,
        "options": RunOptions(plan_review=True, render_fallback=True),
    }
    if topology is None:
        investigate(
            question, client, common.workspace(), run_dir, metrics=common.metrics(), **settings
        )
        return run_dir
    assignment = repo_assignment(configs, client, topology=topology)
    orchestrator = client if topology == "separate" else None
    run_workflow(
        question, client, common.workspace(), run_dir,
        assignment=assignment, orchestrator_client=orchestrator, **settings,
    )  # fmt: skip
    return run_dir


def run_live(question: str) -> Path | None:
    """Show the endpoint controls; on the button, run one bounded investigation."""
    configs = {n: c for n, c in load_providers(common.PROVIDERS).items() if c.enabled}
    planners = [n for n, c in configs.items() if "guard" not in c.logical_model]
    provider = st.selectbox("Meta model endpoint", planners)
    route = st.selectbox("Execution route", list(ROUTES))
    reasoning = st.selectbox("Reasoning strength", ["low", "medium", "high"])
    guards = [n for n, c in configs.items() if "guard" in c.logical_model]
    guard_name = st.selectbox("Safety model (Meta Llama Guard)", [*guards, "none"])
    if not st.button("Run investigation", type="primary"):
        return None
    with st.status("Investigating with a Meta open-weight model...", expanded=True) as status:
        client = build_client(configs[provider])
        guard = _guard(configs, guard_name)
        run_dir = _run(
            question, ROUTES[route], client, configs, guard, reasoning, _listener(status)
        )
        status.update(label="Investigation finished", state="complete")
    return run_dir
