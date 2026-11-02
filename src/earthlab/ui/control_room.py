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
from earthlab.harness.credit import steps
from earthlab.ui import (
    approvals,
    board_view,
    common,
    experiments,
    lab_data,
    provenance,
    scenarios,
    story_view,
)
from earthlab.ui.scenarios import Tile
from earthlab.ui.story_view import Opened, section

APPROVALS_DIR = Path("config/approvals")
ROLE_ORDER = (
    "human_director",
    "orchestrator",
    "product_manager",
    "geospatial_engineer",
    "data_specialist",
    "ml_engineer",
    "implementor",
    "qa_reviewer",
    "scientific_critic",
    "verifier",
    "safety_gate",
    "tool",
)
TELEMETRY = [
    ("Trace JSONL (hash-chained)", "implemented", "Every run; this view reads it."),
    (
        "Prometheus metrics",
        "implemented",
        "Local operator mode only; never public. Worker runs record model use in the trace.",
    ),
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
    cols = st.columns(4)
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
        st.dataframe(event_rows(shown, topology), width="stretch", hide_index=True)
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
        st.dataframe(recorded_approvals(), width="stretch", hide_index=True)
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
                st.dataframe(rows, width="stretch", hide_index=True)
            else:
                st.write("This run asked the approval gate for nothing.")
        if run is not None:
            st.dataframe(_durations(run), width="stretch", hide_index=True)


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
        st.dataframe(view.stages, width="stretch", hide_index=True)
        st.caption("Per-role use, counted from the hash-chained trace:")
        st.dataframe(shown(view.roles), width="stretch", hide_index=True)
        if view.retries:
            st.caption("Failed model calls and retries:")
            st.dataframe(shown(view.retries), width="stretch", hide_index=True)
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


def _gate(opened: Opened) -> None:
    gate = provenance.human_gate(opened.run_dir, opened.entry)
    (st.warning if gate.open else st.info)(f"**{gate.state}.** {gate.detail}")
    if gate.open and common.ui_mode() == "replay":
        st.caption("Nothing can be approved in replay. A decision needs the local operator key.")


def _integrity(opened: Opened) -> None:
    packaging = provenance.is_packaging(opened.entries)
    status = opened.events.status or "unknown"
    usage = scenarios.record_of(opened.run_dir).get("usage") or {}
    story_view.tiles(
        [
            Tile("Trace chain", "Intact", f"{opened.events.trace_records} records"),
            Tile("Trace type", "Packaging" if packaging else "Run's own trace",
                 "not the original job" if packaging else "written during the run"),
            Tile("Run status", status.replace("_", " ").capitalize()),
            Tile("Model calls", str(usage.get("model_calls", "None recorded"))),
        ]
    )  # fmt: skip


def _muse_steps(opened: Opened) -> None:
    rows = []
    for who, what, said in steps(opened.run_dir):
        for role, seat in provenance.MODEL_SEATS.items():
            who = who.replace(f"({role})", f"({seat})")
        rows.append({"Done by": who, "Step": what, "Recorded": said})
    section("What each step really was")
    story_view.table(rows)


def _stages(opened: Opened) -> None:
    rows = provenance.stages(opened.entries)
    section("Stages")
    if rows:
        story_view.table(rows)
    else:
        st.write("No stages are recorded: this trace holds the packaging step only.")


def _decisions(opened: Opened) -> None:
    record = scenarios.record_of(opened.run_dir)
    section("Decision and refusals")
    st.write(
        f"{opened.story.decision}. Code rule outcome: {record.get('code_outcome', 'not recorded')}."
    )
    refusals = record.get("refusal_codes") or []
    if opened.story.key == "S4":
        refusals = [r["code"] for r in scenarios.s4_verdict(opened.run_dir)["refusals"]]
    ready = lab_data.readiness(opened.story.key, opened.run_dir)
    if ready is not None and ready["verification_outcome"] == "refused":
        refusals = [*refusals, f"inference refused: {ready['inference']['note']}"]
    st.write(f"Refusals: {', '.join(refusals) or 'none recorded'}.")


def _story(opened: Opened) -> None:
    st.subheader(opened.story.title)
    _gate(opened)
    if common.ui_mode() == "operator":
        approvals.queue_panel()
    section("Run integrity")
    _integrity(opened)
    section("Who took part")
    record = scenarios.record_of(opened.run_dir)
    story_view.table(provenance.participants(opened.entries, record))
    st.caption(provenance.critic_note(record, opened.entries))
    _stages(opened)
    if opened.story.key == "M1":
        _muse_steps(opened)
    _decisions(opened)
    story_view.identity(opened)


def _classic(picked: tuple[str, Path | None] | None) -> None:
    """Every panel for any recorded run, with the full event timeline."""
    run: RunEvents | None = None
    error: str | None = "No recorded run is available."
    run_dir = None
    if picked is not None:
        st.caption(f"Provenance: {common.run_provenance(picked[1], picked[0])}")
        board_view.run_panel(*picked)
        run_dir, run, error = common.open_run(*picked)
        if run is None and board_view.is_waiting(picked[0]):
            error = "The run has no trace yet."
        elif run is None:
            st.error(f"Run not shown. Integrity check failed: {error}")
    view = load_workflow(run_dir) if run is not None and run_dir is not None else None
    _cards(run, error)
    if view is not None:
        _workflow(view)
    _timeline(run, None if view is None else view.topology)
    approvals.queue_panel()
    if picked is not None:
        experiments.decision_panel(run_dir if picked[1] is not None else None)
    _human_control(run)


def render(label: str | None) -> None:
    st.caption("Who took part, what state the run is in, and what still needs a person.")
    opened = story_view.open_story(label) if label else None
    if opened is not None:
        _story(opened)
        with st.expander("Advanced: full event timeline, roles and approvals"):
            _classic(common.pick_run())
            _topology()
            _telemetry()
        return
    if label is not None and scenarios.key_of(label) is not None:
        return
    _classic(common.pick_run())
    with st.expander("Advanced: roles and telemetry"):
        _topology()
        _telemetry()
