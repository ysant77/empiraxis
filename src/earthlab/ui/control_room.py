"""Axiom Control Room: the director's view of recorded runs.

Events come only from a verified trace, through the EventV1 adapter. Today one Muse
investigator is the only model agent; tools, the verifier and the safety gate are code.
Planned roles are listed and disabled. No conversation is made up.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import streamlit as st
import yaml

from earthlab.events.adapter import RunEvents
from earthlab.events.contract import (
    EXPERIMENTAL_ROLES,
    IMPLEMENTED_ROLES,
    PLANNED_ROLES,
    ROLE_LABELS,
    EventV1,
    is_model_agent,
)
from earthlab.events.redact import visible_events
from earthlab.events.workflow_view import ROLE_NAMES, WorkflowView, load_workflow
from earthlab.ui import common

APPROVALS_DIR = Path("config/approvals")
ROLE_ORDER = (
    "human_director",
    "orchestrator",
    "product_manager",
    "geospatial_engineer",
    "implementor",
    "qa_reviewer",
    "scientific_critic",
    "verifier",
    "safety_gate",
    "tool",
)
TELEMETRY = [
    ("Trace JSONL (hash-chained)", "implemented", "Every run; this view reads it."),
    ("Prometheus metrics", "implemented", "Local operator mode only; never public."),
    ("Grafana dashboard", "planned", "Template only; not deployed."),
    ("Langfuse agent traces", "planned", "Not integrated."),
    ("Agent graph (React Flow)", "planned", "Only after real role separation."),
]


def role_kind(role: str) -> str:
    """How a view must describe an actor. Only a model role is ever called an agent."""
    if is_model_agent(role):
        return "model agent"
    if role in PLANNED_ROLES:
        return "planned role, not running"
    return "human" if role == "human_director" else "code"


def role_name(role: str, topology: str | None = None) -> str:
    """Who an actor was in this run. The orchestrator role id means the single Muse
    investigator outside a workflow, and the model orchestrator in the separate topology."""
    if role == "orchestrator":
        return ROLE_NAMES[role] if topology == "separate" else "Muse investigator (single agent)"
    return ROLE_NAMES.get(role, ROLE_LABELS.get(role, role))


def event_rows(events: list[EventV1], topology: str | None = None) -> list[dict[str, Any]]:
    return [
        {
            "time (UTC)": e.timestamp_utc[11:19],
            "actor": e.actor_role,
            "role in this run": role_name(e.actor_role, topology),
            "actor kind": role_kind(e.actor_role),
            "to": e.receiver_role or "",
            "event": e.event_type,
            "status": e.status,
            "summary": e.message_summary,
            "ms": e.elapsed_ms,
            "trace ref": e.source_trace_ref,
        }
        for e in events
    ]


def _cards(run: RunEvents | None, error: str | None) -> None:
    cols = common.columns(4)
    with cols[0], common.panel("Runtime", "implemented"):
        st.write("The Muse investigator with deterministic tools. The PM path adds model roles.")
    with cols[1], common.panel("Plan critic", "implemented"):
        st.write("Deterministic plan rules, code, not a model. A model critic is not built.")
    with cols[2], common.panel("Trace integrity", "implemented" if run else "unavailable"):
        if run is not None:
            st.write(f"SHA-256 chain verified: {run.trace_records} records.")
            st.caption(f"Head {run.trace_head[:16]}...")
        else:
            st.write(f"Not verified. {error or 'No run selected.'}")
    with cols[3], common.panel("Run access", "implemented"):
        mode = "Read-only replay" if common.ui_mode() == "replay" else "Local operator"
        st.write(f"{mode}. No change to data or models from this view.")


def _topology() -> None:
    with common.panel("Role topology", "implemented", "Planned roles are disabled."):
        for role in ROLE_ORDER:
            state = (
                "current"
                if role in IMPLEMENTED_ROLES
                else "experimental, local live and scripted runs"
                if role in EXPERIMENTAL_ROLES
                else "planned"
            )
            st.write(f"**{ROLE_LABELS[role]}** · {state} · {role_kind(role)}")
            if role in PLANNED_ROLES:
                st.button(f"Open {role.replace('_', ' ')} console", disabled=True, key=role)
        st.caption(
            "The Muse investigator and the deterministic verification path are implemented. "
            "The product manager to engineer workflow, in its combined and separate "
            "topologies, is experimental: scripted runs and a small set of local live runs "
            "are recorded. In the "
            "separate topology, a separately invoked model orchestrator proposes typed "
            "decisions; it is not the single Muse investigator. Implementation workers and "
            "model training are planned. Tools, the plan critic and the verifier are code, "
            "never agent peers."
        )


def _timeline(run: RunEvents | None, topology: str | None = None) -> None:
    with common.panel("Event timeline", "implemented" if run else "unavailable"):
        if run is None:
            st.write("No verified run to show. A broken or missing trace is never displayed.")
            return
        shown, withheld = visible_events(run.events, common.audience())
        state = "closed" if run.closed else "open (no finish record)"
        st.caption(
            f"Recorded events from {run.run_id}; run {state}; status {run.status}. "
            f"{withheld} event(s) withheld for audience {common.audience().value}."
        )
        st.dataframe(event_rows(shown, topology), use_container_width=True, hide_index=True)
        st.caption(
            "Summaries of recorded actions only. Raw prompts and model reasoning are never "
            "shown. No role-to-role conversation is recorded, so none is shown."
        )


def _durations(run: RunEvents) -> list[dict[str, Any]]:
    totals: dict[str, int] = {}
    for event in run.events:
        totals[event.actor_role] = totals.get(event.actor_role, 0) + (event.elapsed_ms or 0)
    return [{"actor": k, "recorded ms": v} for k, v in sorted(totals.items())]


APPROVAL_EVENTS = ("approval_requested", "approval_resolved")


def approval_event_rows(run: RunEvents) -> list[dict[str, Any]]:
    """Approval-gate events recorded in this run's trace, in order."""
    return [
        {
            "event": e.event_type,
            "status": e.status,
            "summary": e.message_summary,
            "trace ref": e.source_trace_ref,
        }
        for e in run.events
        if e.event_type in APPROVAL_EVENTS
    ]


def recorded_approvals(root: Path = APPROVALS_DIR) -> list[dict[str, Any]]:
    """Human approvals recorded in config/approvals, with their expiry state now."""
    rows: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    for path in sorted(root.glob("*.yaml")):
        for item in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("approvals", []):
            expires = datetime.fromisoformat(str(item["expires_at_utc"]).replace("Z", "+00:00"))
            rows.append(
                {
                    "approval": item["approval_id"],
                    "action": item["action"],
                    "approved": item["approved"],
                    "approver": item["approver"],
                    "decided (UTC)": item["decided_at_utc"],
                    "state": "expired" if expires <= now else "in force",
                }
            )
    return rows


def _human_control(run: RunEvents | None) -> None:
    with common.panel("Human control", "implemented", "Recorded approvals, read-only."):
        st.dataframe(recorded_approvals(), use_container_width=True, hide_index=True)
        st.caption("Source: config/approvals. These records are not part of the run trace.")
        st.table(
            [
                {"action": "Data acquisition", "rule": "approval required"},
                {"action": "Paid inference", "rule": "approval required; budget cap per run"},
                {"action": "Untrusted code execution", "rule": "disabled"},
            ]
        )
        if run is not None:
            rows = approval_event_rows(run)
            st.caption("Approval-gate events in this run's trace:")
            if rows:
                st.dataframe(rows, use_container_width=True, hide_index=True)
            else:
                st.write("This run asked the approval gate for nothing.")
        st.button("Approve pending action", disabled=True)
        st.caption(common.status_text("planned", "An approval queue in the UI is not implemented."))
        if run is not None:
            st.dataframe(_durations(run), use_container_width=True, hide_index=True)


def shown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows for display: a value the record does not hold reads "unknown", never zero."""
    return [{k: "unknown" if v is None else v for k, v in row.items()} for row in rows]


PROVENANCE_NOTES = {
    "synthetic": "Synthetic test run: the model replies were scripted. This is not live "
    "multi-agent collaboration and it measures no model.",
    "unknown": "Provenance was not recorded for this run; treat it as unverified.",
    "live": "Live run: every role was served by a model endpoint over HTTP.",
}


def _workflow(view: WorkflowView) -> None:
    with common.panel("Workflow run", "experimental", f"{view.topology} topology"):
        note = PROVENANCE_NOTES[view.provenance]
        (st.info if view.provenance == "live" else st.warning)(note)
        st.caption(f"Run {view.run_id}: status {view.status}. Python validated every step.")
        st.dataframe(view.stages, use_container_width=True, hide_index=True)
        st.caption("Per-role use, counted from the hash-chained trace:")
        st.dataframe(shown(view.roles), use_container_width=True, hide_index=True)
        if view.retries:
            st.caption("Failed model calls and retries:")
            st.dataframe(shown(view.retries), use_container_width=True, hide_index=True)
        else:
            st.caption("No model call failed in this run.")
        st.caption(f"Budget limits: {view.budget['limits']}. Used: {view.budget['used']}.")
        found = ", ".join(view.findings) or "none"
        st.write(
            f"Verified findings: {found}. Limitations: {', '.join(view.limitations) or 'none'}."
        )


def _telemetry() -> None:
    with common.panel("Runtime overview", "implemented"):
        st.table([{"surface": n, "status": s, "note": t} for n, s, t in TELEMETRY])
        st.caption(
            "Never treat agent agreement as proof. The deterministic verifier decides each claim."
        )


def render() -> None:
    common.header(
        "Axiom Control Room",
        "Recorded run chronology, roles, approvals and trace integrity. "
        "No hidden reasoning is shown.",
    )
    common.replay_notice()
    names = common.replay_names()
    run: RunEvents | None = None
    error: str | None = "No recorded run is available."
    if names:
        picked = st.selectbox("Recorded run", names, key="control_run")
        st.caption(f"Provenance: {common.replay_provenance()}")
        run_dir, run, error = common.load_replay(picked)
        if run is None:
            st.error(f"Run not shown. Integrity check failed: {error}")
    view = load_workflow(run_dir) if run is not None and run_dir is not None else None
    _cards(run, error)
    if view is not None:
        _workflow(view)
    _timeline(run, None if view is None else view.topology)
    left, right = common.columns(2)
    with left:
        _topology()
        _telemetry()
    with right:
        _human_control(run)
