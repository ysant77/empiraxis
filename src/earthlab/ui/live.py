"""Live investigation controls for a local operator. A click queues a request; a worker runs it.

The run does not live in this process, so a page refresh neither repeats nor stops it.
"""

from __future__ import annotations

import secrets

import streamlit as st

from earthlab.board.store import Board, RunBusy, RunEntry, RunSpec
from earthlab.board.worker import spawn
from earthlab.llm.providers import load_providers
from earthlab.ui import common
from earthlab.workflow.contracts import Topology

ROUTES: dict[str, Topology | None] = {
    "Direct Muse investigator (baseline)": None,
    "Muse PM, deterministic orchestrator, Muse engineer": "combined",
    "Muse PM, separate LLM orchestrator, Muse engineer": "separate",
}
REQUEST_KEY = "run_request_key"


def queue(board: Board, spec: RunSpec, request_key: str) -> RunEntry | None:
    """Queue one run and start its worker. None when another run is active."""
    try:
        entry, created = board.submit(spec, request_key)
    except RunBusy as busy:
        st.warning(f"Run {busy.run_id} is active. One model serves one run at a time.")
        return None
    if created:
        try:
            spawn(entry.run_id, common.RUNS_DIR)
        except OSError as exc:
            board.end(entry.run_id, "failed", type(exc).__name__)
            raise
    return entry


def submit_live(question: str) -> None:
    """Show the endpoint controls; on the button, queue one bounded investigation."""
    board = common.board()
    if board is None:
        return
    configs = {n: c for n, c in load_providers(common.PROVIDERS).items() if c.enabled}
    planners = [n for n, c in configs.items() if "guard" not in c.logical_model]
    provider = st.selectbox("Meta model endpoint", planners)
    route = st.selectbox("Execution route", list(ROUTES))
    reasoning = st.selectbox("Reasoning strength", ["low", "medium", "high"])
    guards = [n for n, c in configs.items() if "guard" in c.logical_model]
    guard = st.selectbox("Safety model (Meta Llama Guard)", [*guards, "none"])
    if not st.button("Run investigation", type="primary", disabled=board.active() is not None):
        return
    spec = RunSpec(
        question=question,
        topology=ROUTES[route],
        provider=provider,
        guard=guard,
        reasoning=reasoning,
    )
    entry = queue(board, spec, st.session_state.setdefault(REQUEST_KEY, secrets.token_hex(8)))
    if entry is not None:
        del st.session_state[REQUEST_KEY]
        st.session_state[common.SHARED_RUN] = entry.run_id
        st.query_params["run"] = entry.run_id
        st.rerun()
