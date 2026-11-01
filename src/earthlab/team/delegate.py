"""One bounded delegation under a finished run: Lead -> data specialist -> Lead.

The Lead proposes which months need a QA-sensitivity check. Code turns that into a ticket
with fixed owner, checks and limits. The specialist has one read-only tool and one submit
tool; it cannot write a file, reach a network or change a limit. Code recomputes every
row. The Lead may send a passed table back; it cannot pass a failed one. The result never
changes the parent run: it is a new run folder with its own hash-chained trace.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from earthlab.agent.budget import Budget, BudgetMeter, BudgetStop
from earthlab.agent.messages import assistant_message
from earthlab.cases.loader import CaseFile
from earthlab.digest import payload_digest
from earthlab.events.adapter import load_run
from earthlab.llm.client import ChatClient
from earthlab.llm.types import ChatResponse, ProviderError, ToolCall
from earthlab.metrics import EarthlabMetrics
from earthlab.runtime import Workspace
from earthlab.science.burned_area import QaPolicy
from earthlab.team.acceptance import CHECKS, check_table, qa_row
from earthlab.team.contracts import (
    CheckProposal,
    DelegationStatus,
    LeadReview,
    QaRowV1,
    QaTableProposal,
    SpecialistResultV1,
    SpecialistTicketV1,
)
from earthlab.tools.burned_area_tools import pinned_months
from earthlab.trace import RunTrace
from earthlab.workflow.calls import RoleCalls, client_kind
from earthlab.workflow.ledger import WorkflowLedger

LEAD = "geospatial_engineer"
SPECIALIST = "data_specialist"
QA_TOOL = "qa_month_report"
SUBMIT_TABLE = "submit_qa_table"
PROPOSE_CHECK = "propose_qa_check"
REVIEW = "review_qa_table"
SUBMIT_TURNS = 2  # the table, and one spare turn
ARTIFACT_FILE = "qa_table.json"
DEADLINE = timedelta(hours=1)
LEAD_SYSTEM = """\
You are the Geospatial Lead. A finished run reported MCD64A1 burned area under the primary
QA policy. Choose the months whose result needs a check of its sensitivity to the QA
policy. Call propose_qa_check once. Choose only from the listed months. You do not compute
values and you do not grant permissions.
"""
SPECIALIST_SYSTEM = """\
You are a data specialist with one ticket. Call qa_month_report for every month and QA
policy on the ticket. Then call submit_qa_table once, with one row per pair, copying each
value exactly as the tool returned it. Do not estimate or round. Code recomputes every row.
"""
REVIEW_SYSTEM = """\
You are the Geospatial Lead. Read the acceptance checks and the table. Call review_qa_table
once. A failed check cannot be accepted. Do not state any cause or forecast.
"""


class QaArgs(BaseModel):
    month: str
    qa_policy: str


def _schema(name: str, text: str, model: type[BaseModel]) -> dict[str, Any]:
    params = model.model_json_schema()
    params.pop("title", None)
    return {
        "type": "function",
        "function": {"name": name, "description": text, "parameters": params},
    }


class Refused(Exception):
    """A model did not produce a usable proposal within its calls."""


@dataclass(frozen=True)
class Delegation:
    status: DelegationStatus
    ticket: SpecialistTicketV1 | None
    result: SpecialistResultV1 | None
    review: LeadReview | None


def parent_case(parent: Path) -> tuple[str, str, str]:
    """(run_id, trace head, case id) of a verified, closed workflow run. Any doubt raises."""
    run = load_run(parent)
    if not run.closed or run.status is None:
        raise ValueError("the parent run has not finished")
    entries = list(RunTrace(parent / "trace.jsonl").records())
    handoff = next((e for e in entries if e["event"] == "task_handoff"), None)
    if handoff is None:
        raise ValueError("the parent run has no engineering task")
    return run.run_id, run.trace_head, str(handoff["data"]["task"]["case_id"])


class _Flow:
    def __init__(
        self,
        parent: Path,
        lead: ChatClient,
        specialist: ChatClient,
        workspace: Workspace,
        run_dir: Path,
        budget: Budget,
    ):
        if workspace.cases is None:
            raise ValueError("the delegation needs registered cases")
        self.run_id, self.head, case_id = parent_case(parent)
        self.cases = workspace.cases
        self.case_file: CaseFile = workspace.cases.get(case_id)
        self.run_dir, self.budget = run_dir, budget
        self.task_id = f"{run_dir.name.lower()}.lead"
        self.trace = RunTrace(run_dir / "trace.jsonl")
        self.ledger = WorkflowLedger(budget)
        metrics = EarthlabMetrics()
        self.lead = RoleCalls(LEAD, lead, self.trace, metrics, self.ledger)
        self.worker = RoleCalls(SPECIALIST, specialist, self.trace, metrics, self.ledger)
        self.months = pinned_months(self.case_file, self.cases.root)
        self.sources: dict[str, str] = {}

    def _stage(self, turns: int) -> BudgetMeter:
        stage = self.ledger.stage(turns)
        if stage is None:
            raise BudgetStop(self.ledger.why_stopped())
        return BudgetMeter(stage)

    def _invocation(self, phase: str, role: str, task_id: str, status: str | None = None) -> None:
        data: dict[str, Any] = {"phase": phase, "role": role, "task_id": task_id}
        if phase == "finished":
            calls = (self.lead if role == LEAD else self.worker).calls
            data |= {"status": status, "model_calls": calls}
        self.trace.append("role_invocation", "runtime", **data)

    def _ask(self, role: RoleCalls, system: str, user: str, tool: dict[str, Any]) -> ChatResponse:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return role.call(self._stage(1), messages, [tool], "auto")

    def propose(self) -> CheckProposal:
        tool = _schema(PROPOSE_CHECK, "Propose the months to check.", CheckProposal)
        user = json.dumps({"case": self.case_file.case.case_id, "months": self.months})
        resp = self._ask(self.lead, LEAD_SYSTEM, user, tool)
        issues = ["no proposal was submitted"]
        proposal = None
        calls = [c for c in resp.tool_calls if c.name == PROPOSE_CHECK]
        if calls:
            try:
                proposal = CheckProposal.model_validate_json(calls[0].arguments)
                unknown = sorted(set(proposal.months) - set(self.months))
                issues = [f"months not pinned: {unknown}"] if unknown else []
            except ValidationError as exc:
                issues = [e["msg"] for e in exc.errors()][:4]
        self.trace.append(
            "ticket_reviewed", "runtime", task_id=self.task_id, valid=not issues, issues=issues,
            proposal=None if proposal is None else proposal.model_dump(mode="json"),
        )  # fmt: skip
        if proposal is None or issues:
            raise Refused("; ".join(issues))
        return proposal

    def ticket(self, proposal: CheckProposal) -> SpecialistTicketV1:
        months = tuple(sorted(set(proposal.months)))
        policies = tuple(p.value for p in QaPolicy)
        turns = len(months) * len(policies) + SUBMIT_TURNS  # one read per turn must fit
        stage = self.ledger.stage(turns)
        if stage is None or stage.max_turns < turns:
            raise BudgetStop(f"the ticket needs {turns} model calls: {self.ledger.why_stopped()}")
        return SpecialistTicketV1(
            task_id=f"{self.task_id}.data",
            parent_task_id=self.task_id,
            objective="Report the valid-data fraction, gate and area for each month and policy.",
            case_id=self.case_file.case.case_id,
            input_sha256=self.head,
            months=months,
            qa_policies=policies,
            acceptance_checks=CHECKS,
            allowed_tools=(QA_TOOL, SUBMIT_TABLE),
            max_model_calls=stage.max_turns,
            max_tool_calls=stage.max_tool_calls,
            max_seconds=stage.max_seconds,
            max_cost_usd=stage.max_usd,
            deadline_utc=(datetime.now(UTC) + DEADLINE).isoformat(),
        )

    def _tool(self, ticket: SpecialistTicketV1, call: ToolCall) -> dict[str, Any]:
        """Run one allowed read. Anything outside the ticket is rejected and recorded."""
        try:
            args = QaArgs.model_validate_json(call.arguments)
        except ValidationError:
            return self._rejected(call, "arguments do not fit the tool")
        if args.month not in ticket.months or args.qa_policy not in ticket.qa_policies:
            return self._rejected(call, "month or QA policy is not on the ticket")
        row, source = qa_row(self.case_file, self.cases.root, args.month, args.qa_policy)
        self.sources[args.month] = source
        self.trace.append(
            "tool_result", "runtime", name=call.name, outcome="executed", error=None,
            arguments=call.arguments, data={},
        )  # fmt: skip
        return row.model_dump(mode="json")

    def _rejected(self, call: ToolCall, why: str) -> dict[str, Any]:
        self.trace.append(
            "tool_result", "runtime", name=call.name, outcome="rejected", error=why,
            arguments=call.arguments, data={},
        )  # fmt: skip
        return {"error": why}

    def _reply(
        self, ticket: SpecialistTicketV1, messages: list[dict[str, Any]], call: ToolCall
    ) -> None:
        if call.name == QA_TOOL:
            body = self._tool(ticket, call)
        else:
            body = self._rejected(call, f"{call.name} is not on the ticket")
        messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(body)})

    def work(self, ticket: SpecialistTicketV1) -> QaTableProposal | None:
        """The specialist's bounded loop. None when it stops without a usable table."""
        tools = [
            _schema(QA_TOOL, "Read one month under one QA policy.", QaArgs),
            _schema(SUBMIT_TABLE, "Submit the finished table.", QaTableProposal),
        ]
        brief = ticket.model_dump(include={"objective", "months", "qa_policies"})
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SPECIALIST_SYSTEM},
            {"role": "user", "content": json.dumps(brief)},
        ]
        meter = self._stage(ticket.max_model_calls)
        for _ in range(ticket.max_model_calls):
            resp = self.worker.call(meter, messages, tools, "auto")
            messages.append(assistant_message(resp))
            for call in resp.tool_calls:
                if call.name == SUBMIT_TABLE:
                    return self._table(call)
                self._reply(ticket, messages, call)
            if not resp.tool_calls:
                return None
        return None

    def _table(self, call: ToolCall) -> QaTableProposal | None:
        try:
            table = QaTableProposal.model_validate_json(call.arguments)
        except ValidationError:
            self._rejected(call, "the table does not fit the schema")
            return None
        self.trace.append(
            "tool_result", "runtime", name=call.name, outcome="executed", error=None,
            arguments=None, data={},
        )  # fmt: skip
        return table

    def accept(
        self, ticket: SpecialistTicketV1, table: QaTableProposal | None
    ) -> SpecialistResultV1:
        truth: dict[tuple[str, str], QaRowV1] = {}
        for month in ticket.months:
            for policy in ticket.qa_policies:
                truth[(month, policy)], self.sources[month] = qa_row(
                    self.case_file, self.cases.root, month, policy
                )
        rows = () if table is None else table.rows
        acceptance = check_table(ticket.task_id, rows, truth)
        dumped = [r.model_dump(mode="json") for r in rows]
        self.trace.append("acceptance_checked", "verifier", **acceptance.model_dump(mode="json"))
        return SpecialistResultV1(
            task_id=ticket.task_id,
            rows=rows,
            rows_sha256=payload_digest(dumped),
            source_sha256=tuple(sorted(self.sources.values())),
            acceptance=acceptance,
            author=self.worker.identity(),
        )

    def review(self, result: SpecialistResultV1) -> LeadReview | None:
        tool = _schema(REVIEW, "Accept the table or send it back.", LeadReview)
        user = json.dumps(result.model_dump(mode="json", include={"rows", "acceptance"}))
        resp = self._ask(self.lead, REVIEW_SYSTEM, user, tool)
        calls = [c for c in resp.tool_calls if c.name == REVIEW]
        review = None
        if calls:
            try:
                review = LeadReview.model_validate_json(calls[0].arguments)
            except ValidationError:
                review = None
        self.trace.append(
            "lead_reviewed", "runtime", task_id=self.task_id,
            accepted=None if review is None else review.accept,
            overridden=review is not None and review.accept and not result.acceptance.passed,
        )  # fmt: skip
        return review

    def start(self) -> None:
        self.trace.append(
            "delegation_start", "runtime", task_id=self.task_id, parent_run_id=self.run_id,
            parent_trace_head=self.head, case_id=self.case_file.case.case_id,
            lead={"provider": self.lead.client.config.name, "model": self.lead.client.config.model},
            specialist={
                "provider": self.worker.client.config.name,
                "model": self.worker.client.config.model,
            },
            client_kinds={LEAD: client_kind(self.lead.client),
                          SPECIALIST: client_kind(self.worker.client)},
            budget=self.budget.model_dump(),
        )  # fmt: skip

    def finish(
        self,
        status: DelegationStatus,
        reason: str,
        ticket: SpecialistTicketV1 | None = None,
        result: SpecialistResultV1 | None = None,
        review: LeadReview | None = None,
    ) -> Delegation:
        usage = self.ledger.total()
        self.trace.append(
            "finish", "runtime", status=status, reason=reason, workflow=True,
            turns=usage.model_calls,
        )  # fmt: skip
        payload = {
            "status": status,
            "reason": reason,
            "parent_run_id": self.run_id,
            "parent_trace_head": self.head,
            "ticket": None if ticket is None else ticket.model_dump(mode="json"),
            "result": None if result is None else result.model_dump(mode="json"),
            "review": None if review is None else review.model_dump(mode="json"),
        }
        path = self.run_dir / ARTIFACT_FILE if result is not None else None
        if path is not None:
            path.write_text(json.dumps(payload["result"], indent=2), encoding="utf-8")
        (self.run_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return Delegation(status, ticket, result, review)


def _delivered(flow: _Flow, ticket: SpecialistTicketV1, result: SpecialistResultV1) -> None:
    dumped = result.model_dump(mode="json")
    flow.trace.append(
        "result_delivered", "runtime", task_id=ticket.task_id, receiver=LEAD,
        reply_sha256=payload_digest(dumped), reply=dumped,
    )  # fmt: skip


def _handoff(flow: _Flow, ticket: SpecialistTicketV1) -> None:
    dumped = ticket.model_dump(mode="json")
    flow.trace.append(
        "task_handoff", "runtime", task_id=ticket.task_id, parent_task_id=ticket.parent_task_id,
        receiver=SPECIALIST, brief_sha256=ticket.input_sha256,
        task_sha256=payload_digest(dumped), task=dumped,
    )  # fmt: skip


def _steps(flow: _Flow) -> Delegation:
    flow._invocation("started", LEAD, flow.task_id)
    ticket = flow.ticket(flow.propose())
    flow._invocation("finished", LEAD, flow.task_id, "proposed")
    _handoff(flow, ticket)
    flow._invocation("started", SPECIALIST, ticket.task_id)
    result = flow.accept(ticket, flow.work(ticket))
    outcome = "verified" if result.acceptance.passed else "needs_revision"
    flow._invocation("finished", SPECIALIST, ticket.task_id, outcome)
    _delivered(flow, ticket, result)
    review = flow.review(result)
    if not result.acceptance.passed:
        return flow.finish("needs_revision", "an acceptance check failed", ticket, result, review)
    if review is None or not review.accept:
        return flow.finish("needs_revision", "the Lead did not accept", ticket, result, review)
    return flow.finish("verified", "checks passed and the Lead accepted", ticket, result, review)


def run_delegation(
    parent: Path,
    lead: ChatClient,
    specialist: ChatClient,
    workspace: Workspace,
    run_dir: Path,
    budget: Budget | None = None,
) -> Delegation:
    limits = budget or Budget(max_turns=24, max_tool_calls=30, max_seconds=2400.0)
    flow = _Flow(parent, lead, specialist, workspace, run_dir, limits)
    flow.start()
    try:
        return _steps(flow)
    except BudgetStop as stop:
        return flow.finish("budget_exhausted", str(stop))
    except (ProviderError, Refused) as exc:
        return flow.finish("failed", f"{type(exc).__name__}: {str(exc)[:160]}")


def replay_delegation(run_dir: Path, workspace: Workspace) -> dict[str, Any]:
    """Recompute the saved table from pinned files, with no model."""
    if workspace.cases is None:
        raise ValueError("the replay needs registered cases")
    run = load_run(run_dir)
    saved = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    ticket = SpecialistTicketV1.model_validate(saved["ticket"])
    result = SpecialistResultV1.model_validate(saved["result"])
    case = workspace.cases.get(ticket.case_id)
    truth = {
        (month, policy): qa_row(case, workspace.cases.root, month, policy)[0]
        for month in ticket.months
        for policy in ticket.qa_policies
    }
    again = check_table(ticket.task_id, result.rows, truth)
    digest = payload_digest([r.model_dump(mode="json") for r in result.rows])
    return {
        "records": run.trace_records,
        "status": run.status,
        "acceptance_same": again == result.acceptance,
        "rows_hash_same": digest == result.rows_sha256,
        "parent_run_id": saved["parent_run_id"],
    }
