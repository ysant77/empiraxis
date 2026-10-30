"""Regression tests for the failure classes found in the official v1 run.

No held-out question is copied here; each test builds its own case.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import get_args

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say

from earthlab.acquire.gate import ApprovalRefused, authorize, load_approvals
from earthlab.agent.findings import FindingsLedger
from earthlab.agent.loop import RunStatus
from earthlab.cases.models import ApprovalAction
from earthlab.events.adapter import load_run
from earthlab.events.contract import ActorRole, EventV1
from earthlab.llm.types import ProviderError, ProviderErrorKind
from earthlab.metrics import EarthlabMetrics
from earthlab.planning.plan import InvestigationPlan
from earthlab.planning.roles import RoleId
from earthlab.roles import EXPERIMENTAL_ROLES, IMPLEMENTED_ROLES, PLANNED_ROLES
from earthlab.runtime import build_registry, investigate, new_run_dir, open_workspace
from earthlab.trace import RunTrace
from earthlab.ui.control_room import approval_event_rows

ROOT = Path(__file__).resolve().parents[1]
CASE_ID = "kalimantan-2015-burned-area"
APPROVALS = load_approvals(ROOT / "config" / "approvals")
INSIDE = datetime.fromisoformat("2026-10-28T00:00:00+00:00")


def test_month_outside_pinned_data_is_a_typed_result_not_a_crash() -> None:
    registry = build_registry(open_workspace(REPO_DATA), FindingsLedger())
    result = registry.execute(
        "burned_area_summary", json.dumps({"case_id": CASE_ID, "month": "2015-08"})
    )
    assert result.outcome.value == "executed" and result.data is not None
    assert result.data["status"] == "data_unavailable"
    assert result.data["reason_code"] == "data_unavailable"
    assert result.data["pinned_months"] == ["2015-09", "2015-10"]


def test_run_on_a_missing_month_ends_in_a_data_unavailable_abstention(tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            call("burned_area_summary", case_id=CASE_ID, month="2015-12"),
            call(
                "declare_limitation",
                reasons=["data_unavailable"],
                explanation="The pinned data does not hold that month.",
            ),
            say("That month is not in the pinned data, so no area is reported."),
        ]
    )
    workspace = open_workspace(REPO_DATA)
    result = investigate("Burned area in the box in December?", client, workspace, tmp_path)
    assert result.status is RunStatus.ABSTAINED
    assert [r.value for e in result.limitations for r in e.reasons] == ["data_unavailable"]


def test_provider_error_is_counted_but_not_timed(tmp_path: Path) -> None:
    metrics = EarthlabMetrics()
    client = ScriptedClient([ProviderError(ProviderErrorKind.TIMEOUT, "slow")])
    workspace = open_workspace(REPO_DATA)
    result = investigate("q", client, workspace, new_run_dir(tmp_path), metrics=metrics)
    assert result.status is RunStatus.PROVIDER_ERROR
    samples = [s for m in metrics.registry.collect() for s in m.samples]
    requests = [s for s in samples if s.name == "earthlab_inference_requests_total"]
    timed = [s for s in samples if s.name == "earthlab_inference_duration_seconds_count"]
    assert [s.labels["outcome"] for s in requests] == ["timeout"]
    assert sum(s.value for s in timed) == 0


def test_approval_gate_writes_trace_events_the_control_room_shows(tmp_path: Path) -> None:
    run_dir = tmp_path / "gate-run"
    trace = RunTrace(run_dir / "trace.jsonl")
    authorize(APPROVALS, ApprovalAction.CONFIRM_STUDY_AREA, CASE_ID, at=INSIDE, trace=trace)
    with pytest.raises(ApprovalRefused):
        authorize(APPROVALS, ApprovalAction.PUBLISH, CASE_ID, at=INSIDE, trace=trace)
    trace.append("finish", "runtime", status="refused", reason="approval refused", turns=0)
    events = load_run(run_dir).events
    kinds = [(e.event_type, e.status, e.actor_role) for e in events[:4]]
    assert kinds == [
        ("approval_requested", "pending", "system"),
        ("approval_resolved", "approved", "human_director"),
        ("approval_requested", "pending", "system"),
        ("approval_resolved", "rejected", "human_director"),
    ]
    assert "refused" in events[3].message_summary
    rows = approval_event_rows(load_run(run_dir))
    assert [r["status"] for r in rows] == ["pending", "approved", "pending", "rejected"]


def test_one_role_list_and_one_plan_revision_type() -> None:
    assert RoleId is ActorRole
    assert set(get_args(RoleId)) == IMPLEMENTED_ROLES | EXPERIMENTAL_ROLES | PLANNED_ROLES
    assert not EXPERIMENTAL_ROLES & (IMPLEMENTED_ROLES | PLANNED_ROLES)
    event_type = EventV1.model_fields["plan_revision"].annotation
    plan_type = InvestigationPlan.model_fields["plan_revision"].annotation
    assert plan_type is int
    assert event_type == int | None
