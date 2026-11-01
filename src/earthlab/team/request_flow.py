"""One resource request through its model reviews, stopping at the human decision.

The specialist proposes the request's fields; code fixes the identifiers and limits. The
Lead and the PM each make one schema-only call. The source is the local mock server, so
this shows the route, not a real data transfer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError

from earthlab.agent.budget import Budget, BudgetMeter
from earthlab.contracts import Strict
from earthlab.llm.client import ChatClient
from earthlab.llm.types import ChatResponse
from earthlab.metrics import EarthlabMetrics
from earthlab.team.delegate import tool_schema
from earthlab.team.resources import (
    RequestRefused,
    RequestView,
    ResourceDesk,
    ResourceRequestV1,
    ReviewRole,
)
from earthlab.trace import RunTrace
from earthlab.workflow.calls import RoleCalls
from earthlab.workflow.ledger import WorkflowLedger

EXPIRES = timedelta(hours=24)
ASK = "propose_resource_request"
ENDORSE = "endorse_request"
ASK_SYSTEM = """\
You are a data specialist. Your ticket needs the resource described below, and you do not
have it. Call propose_resource_request once. Name the credential it needs, if any, by its
name only. You never see or handle a secret value.
"""
LEAD_SYSTEM = """\
You are the Geospatial Lead. Check that this request has a real scientific or technical
need for its parent task. Call endorse_request once. You grant no permission: a person
decides after the product manager.
"""
PM_SYSTEM = """\
You are the product manager. Check the scope, priority and cost of this request. Call
endorse_request once. You grant no permission: a person makes the decision.
"""


class RequestProposal(Strict):
    """What the specialist model submits. The URL and the limits come from the catalogue."""

    purpose: str = Field(min_length=5, max_length=300)
    scientific_need: str = Field(min_length=5, max_length=300)
    risk: str = Field(min_length=3, max_length=200)
    alternatives: tuple[str, ...] = Field(default=(), max_length=4)


class Endorsement(Strict):
    endorse: bool
    note: str = Field(min_length=3, max_length=300)


def _call(role: RoleCalls, system: str, user: str, tool: dict[str, Any]) -> ChatResponse:
    meter = BudgetMeter(Budget(max_turns=1, max_tool_calls=1, max_seconds=600.0))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return role.call(meter, messages, [tool], "auto")


def _argument(resp: ChatResponse, name: str) -> str | None:
    return next((c.arguments for c in resp.tool_calls if c.name == name), None)


def propose(role: RoleCalls, need: dict[str, Any]) -> RequestProposal:
    tool = tool_schema(ASK, "Propose the resource request.", RequestProposal)
    raw = _argument(_call(role, ASK_SYSTEM, json.dumps(need), tool), ASK)
    if raw is None:
        raise RequestRefused("the specialist proposed no request")
    try:
        return RequestProposal.model_validate_json(raw)
    except ValidationError as exc:
        raise RequestRefused(f"the proposal does not fit: {exc.errors()[0]['msg']}") from None


def _review(
    desk: ResourceDesk, role: RoleCalls, who: ReviewRole, system: str, view: RequestView
) -> RequestView:
    tool = tool_schema(ENDORSE, "Endorse or refuse the request.", Endorsement)
    user = view.request.model_dump_json()
    raw = _argument(_call(role, system, user, tool), ENDORSE)
    served = role.served_model or role.client.config.model
    if raw is None:
        return desk.review(view.request.request_id, who, served, False, "no endorsement submitted")
    try:
        answer = Endorsement.model_validate_json(raw)
    except ValidationError:
        return desk.review(view.request.request_id, who, served, False, "unusable endorsement")
    return desk.review(view.request.request_id, who, served, answer.endorse, answer.note)


def run_request(
    runs_dir: Path, client: ChatClient, need: dict[str, Any], request_id: str, parent_task: str
) -> RequestView:
    """Propose and review one request. It stops at pm_endorsed, or earlier on a refusal."""
    folder = runs_dir / "requests" / f"{request_id}.models"
    trace = RunTrace(folder / "trace.jsonl")
    ledger, metrics = WorkflowLedger(Budget(max_turns=3)), EarthlabMetrics()
    roles = {
        name: RoleCalls(name, client, trace, metrics, ledger)
        for name in ("data_specialist", "geospatial_engineer", "product_manager")
    }
    proposal = propose(roles["data_specialist"], need)
    request = ResourceRequestV1(
        request_id=request_id,
        parent_task_id=parent_task,
        purpose=proposal.purpose,
        asset=str(need["asset"]),
        url=str(need["url"]),
        max_bytes=int(need["max_bytes"]),
        expected_sha256=need.get("sha256"),
        content_types=tuple(need["content_types"]),
        license_terms=str(need["license_terms"]),
        credential_name=need.get("credential_name"),
        expires_utc=datetime.now(UTC) + EXPIRES,
        alternatives=proposal.alternatives,
        scientific_need=proposal.scientific_need,
        risk=proposal.risk,
    )
    desk = ResourceDesk(runs_dir)
    view = _review(
        desk, roles["geospatial_engineer"], "geospatial_engineer", LEAD_SYSTEM, desk.open(request)
    )
    if view.status == "lead_endorsed":
        view = _review(desk, roles["product_manager"], "product_manager", PM_SYSTEM, view)
    return view
