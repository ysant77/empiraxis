"""Live investigation controls for a local operator. Only operator mode calls run_live."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from earthlab.agent.budget import Budget
from earthlab.llm.client import build_client
from earthlab.llm.providers import load_providers
from earthlab.llm.raw import RawCompletionClient
from earthlab.runtime import investigate, new_run_dir
from earthlab.safety.llama_guard import LlamaGuard
from earthlab.ui import common


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

    return listener


def run_live(question: str) -> Path | None:
    """Show the endpoint controls; on the button, run one bounded investigation."""
    configs = {n: c for n, c in load_providers(common.PROVIDERS).items() if c.enabled}
    planners = [n for n, c in configs.items() if "guard" not in c.logical_model]
    provider = st.selectbox("Meta model endpoint", planners)
    reasoning = st.selectbox("Reasoning strength", ["low", "medium", "high"])
    guards = [n for n, c in configs.items() if "guard" in c.logical_model]
    guard_name = st.selectbox("Safety model (Meta Llama Guard)", [*guards, "none"])
    if not st.button("Run investigation", type="primary"):
        return None
    guard = (
        None
        if guard_name == "none"
        else LlamaGuard(RawCompletionClient(configs[guard_name]), configs[guard_name].logical_model)
    )
    run_dir = new_run_dir(common.RUNS_DIR)
    with st.status("Investigating with a Meta open-weight model...", expanded=True) as status:
        investigate(
            question,
            build_client(configs[provider]),
            common.workspace(),
            run_dir,
            metrics=common.metrics(),
            budget=Budget(),
            reasoning=reasoning,
            listener=_listener(status),
            guard=guard,
        )
        status.update(label="Investigation finished", state="complete")
    return run_dir
