"""The one panel every surface shows for the selected run: state, stage and task tree.

Stage and tasks are computed from the verified trace; the board adds only whether a worker
is alive. A view never writes a status. While a run is active the panel polls.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import streamlit as st

from earthlab.board.progress import IllegalMove, Progress, TaskRow, fold
from earthlab.board.store import RunEntry
from earthlab.trace import RunTrace, TraceIntegrityError
from earthlab.ui import common

POLL_SECONDS = 3
NOTES_SHOWN = 8
READ_TRIES = 3
SURFACES = {
    "workspace": "Research Workspace",
    "control": "Control Room",
    "lab": "Engineering Lab",
}


def read_trace(run_dir: Path) -> list[dict[str, Any]]:
    """Verified records so far. A line still being written gets a short retry."""
    path = run_dir / "trace.jsonl"
    if not path.is_file():
        return []
    for attempt in range(READ_TRIES):
        try:
            trace = RunTrace(path)
            trace.verify()
            return list(trace.records())
        except (TraceIntegrityError, KeyError) as exc:
            if attempt == READ_TRIES - 1:
                raise TraceIntegrityError(f"{type(exc).__name__}: {exc}") from exc
            time.sleep(0.05)
    return []


def task_rows(tasks: dict[str, TaskRow]) -> list[dict[str, Any]]:
    return [
        {
            "task": t.task_id,
            "parent": t.parent_task_id or "",
            "owner": t.owner,
            "status": t.status,
            "outcome": t.outcome or "",
            "blocked reason": t.blocked_reason or "",
            "input sha256": (t.input_sha256 or "")[:16],
            "output sha256": (t.output_sha256 or "")[:16],
        }
        for t in tasks.values()
    ]


def entry_for(label: str) -> RunEntry | None:
    board = common.board()
    return None if board is None else board.get(label)


def is_waiting(label: str) -> bool:
    """True while a run has no trace to open yet, so a view must not call that a failure."""
    entry = entry_for(label)
    return entry is not None and entry.active


def links(label: str) -> None:
    """The same run on each surface. Any browser session can open these links."""
    parts = [f"[{name}](?view={key}&run={quote(label, safe='')})" for key, name in SURFACES.items()]
    st.caption("Open this run in: " + " · ".join(parts))


def _waiting_note(entries: list[dict[str, Any]], entry: RunEntry) -> str:
    now = time.time()
    beat = "no heartbeat yet" if entry.beat_at is None else f"{now - entry.beat_at:.0f} s ago"
    if not entries:
        return f"Worker heartbeat {beat}. No trace record yet."
    last = datetime.fromisoformat(str(entries[-1]["ts"])).timestamp()
    return f"Worker heartbeat {beat}. Last trace record {now - last:.0f} s ago."


def _state_line(entry: RunEntry | None, view: Progress) -> str:
    worker = "no local worker record" if entry is None else f"worker {entry.state}"
    outcome = view.status or "not finished"
    return f"**{view.run_id}**: {worker}; trace status {outcome}; {view.stage}."


def _facts(view: Progress) -> None:
    st.caption(
        f"Trace head {view.head[:16] or 'none'}, {view.records} records. "
        f"{view.model_calls} model calls, {view.tool_calls} tool calls, "
        f"{view.prompt_tokens} prompt and {view.completion_tokens} completion tokens."
    )


def _draw(label: str, run_dir: Path, entry: RunEntry | None) -> None:
    entries = read_trace(run_dir)
    view = fold(run_dir.name, entries)
    st.write(_state_line(entry, view))
    if entry is not None and entry.active:
        st.caption(_waiting_note(entries, entry))
    if entry is not None and entry.note:
        st.warning(f"Worker note: {entry.note}. The trace shows only what was recorded.")
    _facts(view)
    if view.tasks:
        st.dataframe(task_rows(view.tasks), width="stretch", hide_index=True)
    if entry is not None and entry.active and view.notes:
        st.table([{"recent step": note} for note in view.notes[-NOTES_SHOWN:]])
    links(label)


@st.fragment(run_every=POLL_SECONDS)
def _live(label: str, run_dir: Path) -> None:
    entry = entry_for(label)
    if entry is None or not entry.active:
        st.rerun()
    _draw(label, run_dir, entry)


def run_panel(label: str, local: Path | None) -> None:
    """Show the selected run. It polls until the worker ends, then the page redraws."""
    entry = entry_for(label)
    live = entry is not None and entry.active
    title = "Run in progress" if live else "Run state"
    with common.panel(title, "experimental", "Computed from the hash-chained trace."):
        note = common.scenario_note(label)
        if note is not None:
            st.caption(note)
        if local is None and entry is None:
            run_dir, _, error = common.open_run(label, None)
            if run_dir is None:
                st.write(f"No verified run to show: {error}")
                return
            local = run_dir
        if local is None:
            return
        try:
            if live:
                _live(label, local)
            else:
                _draw(label, local, entry)
        except (TraceIntegrityError, IllegalMove) as exc:
            st.error(f"Run state not shown: {type(exc).__name__}: {exc}")


def banner() -> None:
    """Every surface says so when a run is active, in any browser session."""
    board = common.board()
    active = None if board is None else board.active()
    if active is not None:
        st.info(f"Run {active.run_id} is {active.state}. One model serves one run at a time.")
        links(active.run_id)
