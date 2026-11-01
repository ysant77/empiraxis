"""The Human Director's queue for resource requests, in the Control Room.

The key field is not a chat box: its value goes only to the code that signs the decision,
and no model sees it. Secret values are never entered here. A credential is set in the
operator's own environment, and this view shows only its name.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from earthlab.team.broker import Broker
from earthlab.team.resources import RequestRefused, RequestView, ResourceDesk, operator_key
from earthlab.ui import common

APPROVER = "local operator (holder of the operator key)"


def request_rows(views: list[RequestView]) -> list[dict[str, Any]]:
    return [
        {
            "request": v.request.request_id,
            "status": v.status,
            "asset": v.request.asset,
            "domain": v.request.domain,
            "max bytes": v.request.max_bytes,
            "credential": v.request.credential_name or "none",
            "expected USD": v.request.expected_usd,
            "license": v.request.license_terms,
            "reviewers": "; ".join(v.reviewers),
            "reason": v.reason or "",
            "approval sha256": (v.approval_sha256 or "")[:16],
            "fetched sha256": str((v.fetched or {}).get("sha256", ""))[:16],
        }
        for v in views
    ]


def _decide(desk: ResourceDesk, view: RequestView, key: str, approve: bool) -> None:
    request_id = view.request.request_id
    try:
        done = desk.decide(request_id, approve, key, APPROVER)
        if approve:
            done = Broker(desk, common.RUNS_DIR).fetch_approved(request_id)
    except RequestRefused as refused:
        st.error(f"Refused: {refused}")
        return
    st.success(f"Request {request_id}: {done.status}.")


def _card(desk: ResourceDesk, view: RequestView) -> None:
    request = view.request
    st.markdown(f"**{request.request_id}**: {request.purpose}")
    st.caption(
        f"Need: {request.scientific_need} Risk: {request.risk} URL: {request.url}. "
        f"Limit: {request.max_bytes} bytes. Expires {request.expires_utc:%Y-%m-%d %H:%M} UTC."
    )
    if request.credential_name is not None:
        st.warning(
            f"credential_required: {request.credential_name}. Set it in the operator "
            "environment before you approve. Never enter a secret here or in chat."
        )
    key = st.text_input("Operator key", type="password", key=f"key-{request.request_id}")
    approve, deny = common.columns(2)
    if approve.button("Approve", key=f"approve-{request.request_id}", disabled=not key):
        _decide(desk, view, key, True)
    if deny.button("Deny", key=f"deny-{request.request_id}", disabled=not key):
        _decide(desk, view, key, False)


def queue_panel() -> None:
    """Shown to a local operator only. Replay mode has no queue and no control."""
    if common.ui_mode() != "operator":
        return
    desk = ResourceDesk(common.RUNS_DIR)
    views = desk.all()
    with common.panel("Resource requests", "experimental", "Specialist, Lead, PM, then a person."):
        if not views:
            st.write("No resource request is recorded.")
            return
        st.dataframe(request_rows(views), use_container_width=True, hide_index=True)
        pending = [v for v in views if v.status == "pm_endorsed"]
        if pending and operator_key() is None:
            st.warning("No operator key is set, so a request cannot be decided here.")
            return
        for view in pending:
            _card(desk, view)
