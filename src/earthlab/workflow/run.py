"""One research request through the product manager and the Geospatial Engineer.

The Python controller here owns every transition, permission and limit:

received -> safety gate -> PM brief (one model call, one correction) -> brief validated
-> [separate topology: orchestrator decision (one call, one correction) -> validated]
-> needs_input | out_of_scope | engineering task -> engineer run (the existing plan-
reviewed investigator, limited to the assigned case) -> verified result to the PM -> PM
report (audited; else the engineer's audited answer) -> finished.

The product manager has one schema-only tool and never sees a scientific tool. The
engineer is the existing investigator with plan review on, scoped to its case's tools and
datasets. Both roles share one budget (WorkflowLedger) and trace into one hash chain. Both
roles must be bound (WorkflowAssignment) to the clients that serve them.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from earthlab.agent.budget import Budget, BudgetMeter, BudgetStop
from earthlab.agent.loop import Investigation, RunStatus
from earthlab.agent.rendered import verified_block
from earthlab.cases.tools import CaseLibrary
from earthlab.digest import payload_digest
from earthlab.llm.client import ChatClient
from earthlab.llm.retry import NO_RETRY
from earthlab.llm.types import ProviderError
from earthlab.metrics import EarthlabMetrics
from earthlab.runtime import DEFAULT_OPTIONS, RunOptions, Workspace, investigate, result_payload
from earthlab.safety.gate import SafetyGate
from earthlab.safety.llama_guard import LlamaGuard
from earthlab.trace import RunTrace
from earthlab.verify.answer_audit import audit_answer
from earthlab.verify.claims import Verdict
from earthlab.workflow.assign import WorkflowAssignment, task_scope
from earthlab.workflow.brief import PM_CALLS, fixed_report, propose_brief, validate_brief
from earthlab.workflow.calls import RoleCalls, client_kind
from earthlab.workflow.contracts import (
    EngineeringReplyV1,
    EngineeringTaskV1,
    ManagerResultV1,
    OrchestratorDecisionV1,
    ProductBriefV1,
    RoleCall,
    WorkflowStatus,
)
from earthlab.workflow.ledger import WorkflowLedger
from earthlab.workflow.orchestrate import ORCHESTRATOR_CALLS, propose_decision
from earthlab.workflow.prompts import PM_REPORT, engineer_prompt

__all__ = ["WorkflowRun", "engineering_task", "run_workflow", "validate_brief"]

_REPORTABLE = (RunStatus.VERIFIED, RunStatus.PARTIAL, RunStatus.ABSTAINED)


@dataclass(frozen=True)
class WorkflowRun:
    status: WorkflowStatus
    brief: ProductBriefV1 | None
    task: EngineeringTaskV1 | None
    reply: EngineeringReplyV1 | None
    manager: ManagerResultV1
    engineer: Investigation | None
    pm_calls: int


@dataclass(frozen=True)
class _Setup:
    question: str
    client: ChatClient
    workspace: Workspace
    run_dir: Path
    metrics: EarthlabMetrics
    budget: Budget
    reasoning: str
    listener: Callable[[dict[str, Any]], None] | None
    guard: LlamaGuard | None
    options: RunOptions
    assignment: WorkflowAssignment
    orchestrator: ChatClient | None = None


def engineering_task(
    brief: ProductBriefV1, cases: CaseLibrary, budget: Budget
) -> EngineeringTaskV1:
    case_file = cases.get(str(brief.brief.case_id))
    scope = task_scope(case_file)
    return EngineeringTaskV1(
        task_id=f"{brief.task_id}.ge",
        parent_task_id=brief.task_id,
        brief_sha256=payload_digest(brief.model_dump(mode="json")),
        objective=brief.brief.normalized_question,
        case_id=case_file.case.case_id,
        allowed_dataset_ids=tuple(sorted(case_file.assets)),
        allowed_method_ids=(case_file.case.method_id,),
        allowed_tool_names=tuple(sorted(scope.tools)),
        max_model_calls=budget.max_turns,
        max_tool_calls=budget.max_tool_calls,
        max_seconds=budget.max_seconds,
        max_cost_usd=budget.max_usd,
    )


def _only(cases: CaseLibrary, case_id: str) -> CaseLibrary:
    """A library holding one case, so the engineer cannot plan or claim outside it."""
    files = {case_id: cases.files[case_id]} if case_id in cases.files else {}
    return CaseLibrary({case_id: cases.get(case_id)}, cases.root, files)


def _supported(result: Investigation) -> tuple[list[str], set[str]]:
    pm25 = [i for i, r in result.ledger.latest_by_id().items() if r.verdict is Verdict.SUPPORTED]
    area = {
        i for i, r in result.area_ledger.latest_by_id().items() if r.verdict is Verdict.SUPPORTED
    }
    return pm25, area


def _reply(
    task: EngineeringTaskV1, result: Investigation, ms: int, author: RoleCall
) -> EngineeringReplyV1:
    pm25, area = _supported(result)
    return EngineeringReplyV1(
        task_id=task.task_id,
        status=result.status.value,
        plan_sha256=tuple(r.plan_sha256 for r in result.plan_reviews),
        critic_verdicts=tuple(r.verdict for r in result.plan_reviews),
        supported_finding_ids=tuple(sorted([*pm25, *area])),
        limitation_reasons=tuple(
            sorted({c.value for entry in result.limitations for c in entry.reasons})
        ),
        elapsed_ms=ms,
        author=author,
    )


class _Flow:
    """The controller for one run. Each method is one stage; each stage is traced."""

    def __init__(self, setup: _Setup, pm_client: ChatClient):
        self.s = setup
        self.trace = RunTrace(setup.run_dir / "trace.jsonl", setup.listener)
        slug = re.sub(r"[^a-z0-9._-]", "-", setup.run_dir.name.lower()).lstrip("-._")
        self.task_id = slug or "run"
        self.ledger = WorkflowLedger(setup.budget)
        retry = setup.options.provider_retry or NO_RETRY
        self.pm = RoleCalls(
            "product_manager", pm_client, self.trace, setup.metrics, self.ledger, retry
        )
        self.orch = (
            None
            if setup.orchestrator is None
            else RoleCalls(
                "orchestrator", setup.orchestrator, self.trace, setup.metrics, self.ledger, retry
            )
        )
        self.decision: OrchestratorDecisionV1 | None = None
        self.gate = SafetyGate(setup.guard, setup.metrics, self.trace)

    @property
    def cases(self) -> CaseLibrary:
        cases = self.s.workspace.cases
        if cases is None:
            raise ValueError("the workflow needs registered cases")
        return cases

    def run(self) -> WorkflowRun:
        s, pm = self.s, self.pm.client.config
        self.trace.append(
            "workflow_start", "runtime", question=s.question, task_id=self.task_id,
            topology=s.assignment.topology, pm={"provider": pm.name, "model": pm.model},
            engineer={"provider": s.client.config.name, "model": s.client.config.model},
            bindings=s.assignment.records(),
            client_kinds={role: client_kind(c) for role, c in self._clients().items()},
            budget=s.budget.model_dump(), retry_policy=self.pm.retry.record(),
        )  # fmt: skip
        asked = self.gate.check_question(s.question)
        if not asked.allowed or asked.causal_only():
            return self._without_models()
        brief, issues, status = self._brief()
        if brief is None:
            failed = ManagerResultV1(
                task_id=self.task_id, status=status, typed_limitations=tuple(issues)
            )
            return self._finish(failed)
        if brief.brief.route != "engineer":
            stop = ManagerResultV1(
                task_id=self.task_id,
                status=brief.brief.route,
                followup_questions=brief.brief.clarifications_needed,
            )
            return self._finish(stop, brief)
        if self.orch is not None:
            stopped = self._orchestrate(brief)
            if stopped is not None:
                return self._finish(stopped, brief)
        return self._engineer(brief)

    def _clients(self) -> dict[str, ChatClient]:
        found = {"product_manager": self.pm.client, "geospatial_engineer": self.s.client}
        return found | ({"orchestrator": self.orch.client} if self.orch else {})

    def _orchestrate(self, brief: ProductBriefV1) -> ManagerResultV1 | None:
        """Run the separate orchestrator; None means assign the engineer."""
        if self.orch is None:
            raise RuntimeError("only the separate topology has an orchestrator")
        stage = self.ledger.stage(ORCHESTRATOR_CALLS)
        status: WorkflowStatus = "failed"
        issues: list[str] = []
        self._invocation("started", "orchestrator", brief.task_id)
        started = self.ledger.elapsed()
        try:
            if stage is None:
                raise BudgetStop(self.ledger.why_stopped())
            self.decision, issues = propose_decision(self.orch, brief, self.s.question, stage)
        except BudgetStop as exc:
            issues, status = [str(exc)], "budget_exhausted"
        except ProviderError as exc:
            issues, status = [str(exc)], "provider_error"
        self.ledger.charge("orchestrator", seconds=self.ledger.elapsed() - started)
        done = status if self.decision is None else "completed"
        self._invocation("finished", "orchestrator", brief.task_id, done, self.orch.calls)
        if self.decision is None:
            return ManagerResultV1(
                task_id=self.task_id, status=status, typed_limitations=tuple(issues)
            )
        choice = self.decision.decision
        if choice.decision == "request_input":
            followup = (choice.clarification or "",)
            return ManagerResultV1(
                task_id=self.task_id, status="needs_input", followup_questions=followup
            )
        if choice.decision == "decline":
            return ManagerResultV1(
                task_id=self.task_id, status="out_of_scope", typed_limitations=(choice.reason,)
            )
        return None

    def _without_models(self) -> WorkflowRun:
        """Refusals and causal abstentions never reach a model; investigate records them."""
        s = self.s
        result = investigate(
            s.question, s.client, s.workspace, s.run_dir, metrics=s.metrics, guard=s.guard
        )
        self.trace.resync()
        manager = ManagerResultV1(
            task_id=self.task_id,
            status=result.status.value,
            report_text=result.answer,
            findings_text=verified_block(result.ledger, result.area_ledger, result.limitations),
            report_source="engineer" if result.answer else "none",
        )
        return self._finish(manager, result=result)

    def _brief(self) -> tuple[ProductBriefV1 | None, list[str], WorkflowStatus]:
        """The validated brief, or None with its issues and the failed status."""
        stage = self.ledger.stage(PM_CALLS)
        if stage is None:
            return None, [self.ledger.why_stopped()], "budget_exhausted"
        self._invocation("started", "product_manager", self.task_id)
        started = self.ledger.elapsed()
        status: WorkflowStatus = "failed"
        try:
            brief, issues = propose_brief(
                self.pm,
                self.s.question,
                self.cases,
                stage,
                self.task_id,
                self.s.assignment.topology,
            )
        except BudgetStop as exc:
            brief, issues, status = None, [str(exc)], "budget_exhausted"
        except ProviderError as exc:
            brief, issues, status = None, [str(exc)], "provider_error"
        self.ledger.charge("product_manager", seconds=self.ledger.elapsed() - started)
        done = "completed" if brief is not None else status
        self._invocation("finished", "product_manager", self.task_id, done, self.pm.calls)
        return brief, issues, status

    def _invocation(
        self, phase: str, role: str, task_id: str, status: str | None = None, calls: int = 0
    ) -> None:
        data: dict[str, Any] = {"phase": phase, "role": role, "task_id": task_id}
        if phase == "finished":
            data |= {"status": status, "model_calls": calls}
        self.trace.append("role_invocation", "runtime", **data)

    def _engineer(self, brief: ProductBriefV1) -> WorkflowRun:
        s = self.s
        stage = self.ledger.stage()
        if stage is None:
            stop = ManagerResultV1(
                task_id=self.task_id,
                status="budget_exhausted",
                typed_limitations=(self.ledger.why_stopped(),),
            )
            return self._finish(stop, brief)
        case_file = self.cases.get(str(brief.brief.case_id))
        task = engineering_task(brief, self.cases, stage)
        dumped = task.model_dump(mode="json")
        self.trace.append(
            "task_handoff", "runtime", task_id=task.task_id, parent_task_id=task.parent_task_id,
            receiver="geospatial_engineer", brief_sha256=task.brief_sha256,
            task_sha256=payload_digest(dumped), task=dumped,
        )  # fmt: skip
        self._invocation("started", "geospatial_engineer", task.task_id)
        started = time.perf_counter()
        result = investigate(
            engineer_prompt(task, brief, s.question),
            s.client,
            replace(s.workspace, cases=_only(self.cases, task.case_id)),
            s.run_dir,
            metrics=s.metrics,
            budget=stage,
            reasoning=s.reasoning,
            listener=s.listener,
            guard=s.guard,
            options=replace(s.options, plan_review=True, scope=task_scope(case_file)),
        )
        self.trace.resync()  # investigate appended to the same file through its own handle
        self.ledger.charge(
            "geospatial_engineer", model_calls=result.turns, tool_calls=result.tool_calls,
            prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
            cost_usd=result.cost_usd or 0.0, seconds=result.seconds,
        )  # fmt: skip
        reply = self._deliver(task, result, round((time.perf_counter() - started) * 1000))
        return self._finish(self._manager(reply, result), brief, task, reply, result)

    def _manager(self, reply: EngineeringReplyV1, result: Investigation) -> ManagerResultV1:
        source, text = self._report(reply, result)
        return ManagerResultV1(
            task_id=self.task_id,
            status=reply.status,
            verified_finding_refs=reply.supported_finding_ids,
            typed_limitations=reply.limitation_reasons,
            report_text=text,
            findings_text=verified_block(result.ledger, result.area_ledger, result.limitations),
            report_source=source,
            source_hashes=(self.s.workspace.snapshot.sha256,),
        )

    def _deliver(
        self, task: EngineeringTaskV1, result: Investigation, ms: int
    ) -> EngineeringReplyV1:
        cfg = self.s.client.config
        author = RoleCall.model_validate(
            {
                "role_id": "geospatial_engineer",
                "provider": cfg.name,
                "model": cfg.model,
                "logical_model": cfg.logical_model,
                "served_model": result.served_model,
            }
        )
        reply = _reply(task, result, ms, author)
        self._invocation(
            "finished", "geospatial_engineer", task.task_id, reply.status, result.turns
        )
        dumped = reply.model_dump(mode="json")
        self.trace.append(
            "result_delivered", "runtime", task_id=task.task_id, receiver="product_manager",
            reply_sha256=payload_digest(dumped), reply=dumped,
        )  # fmt: skip
        return reply

    def _report(self, reply: EngineeringReplyV1, result: Investigation) -> tuple[str, str]:
        """The PM's report and its source, else the engineer's audited answer.

        Only verified, partial and abstained runs have an audited answer; others report no text.
        """
        if result.status not in _REPORTABLE or not result.answer:
            return ("none", "")
        fallback = ("rendered" if result.answer_source == "rendered" else "engineer", result.answer)
        envelope = {
            "status": reply.status,
            "verified_finding_ids": list(reply.supported_finding_ids),
            "declared_limitations": list(reply.limitation_reasons),
            "engineer_answer": result.answer,
        }
        messages = [
            {"role": "system", "content": PM_REPORT},
            {"role": "user", "content": json.dumps(envelope)},
        ]
        stage = self.ledger.stage(1)
        started = self.ledger.elapsed()
        try:
            if stage is None:
                raise BudgetStop(self.ledger.why_stopped())
            text = self.pm.call(BudgetMeter(stage), messages, [], "none").content.strip()
            issues = self._report_issues(text, result)
        except (ProviderError, BudgetStop) as exc:
            text, issues = "", [str(exc)]
        self.ledger.charge("product_manager", seconds=self.ledger.elapsed() - started)
        source = "pm_model" if not issues else fallback[0]
        self.trace.append("pm_report", "runtime", passed=not issues, issues=issues, source=source)
        return (source, text) if not issues else fallback

    def _report_issues(self, text: str, result: Investigation) -> list[str]:
        if not text:
            return ["the report is empty"]
        _, area = _supported(result)
        bound = result.area_ledger.covers_quality()
        issues = audit_answer(text, result.ledger.latest_by_id(), area, bound).problems()
        if issues:
            return issues
        decision = self.gate.check_answer(self.s.question, text)
        return [] if decision.allowed else [f"safety gate: {decision.reason}"]

    def _finish(
        self,
        manager: ManagerResultV1,
        brief: ProductBriefV1 | None = None,
        task: EngineeringTaskV1 | None = None,
        reply: EngineeringReplyV1 | None = None,
        result: Investigation | None = None,
    ) -> WorkflowRun:
        s, manager = self.s, fixed_report(manager, brief)
        self.trace.append(
            "finish", "runtime", status=manager.status, reason=f"workflow {manager.status}",
            workflow=True, turns=self.pm.calls + (result.turns if result else 0),
            report_source=manager.report_source,
        )  # fmt: skip
        payload = (
            result_payload(s.question, result, s.workspace.snapshot, s.workspace.cases)
            if result is not None
            else {"question": s.question, "source": s.workspace.snapshot.citation()}
        )
        payload |= {"status": manager.status, "workflow": self._block(manager, brief, task, reply)}
        path = s.run_dir / "result.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), "utf-8")
        tmp.replace(path)
        return WorkflowRun(manager.status, brief, task, reply, manager, result, self.pm.calls)

    def _block(
        self,
        manager: ManagerResultV1,
        brief: ProductBriefV1 | None,
        task: EngineeringTaskV1 | None,
        reply: EngineeringReplyV1 | None,
    ) -> dict[str, Any]:
        def dump(record: Any) -> Any:
            return None if record is None else record.model_dump(mode="json")

        usage = {role: vars(u) for role, u in self.ledger.usage.items()}
        return {
            "topology": self.s.assignment.topology,
            "bindings": self.s.assignment.records(),
            "orchestrator_decision": None
            if self.decision is None
            else self.decision.model_dump(mode="json"),
            "usage": usage | {"total": vars(self.ledger.total())},
            "budget": self.s.budget.model_dump(),
            "pm_calls": self.pm.calls,
            "brief": dump(brief),
            "engineering_task": dump(task),
            "engineering_reply": dump(reply),
            "manager_result": dump(manager),
        }


def run_workflow(
    question: str,
    client: ChatClient,
    workspace: Workspace,
    run_dir: Path,
    *,
    assignment: WorkflowAssignment,
    pm_client: ChatClient | None = None,
    orchestrator_client: ChatClient | None = None,
    metrics: EarthlabMetrics | None = None,
    budget: Budget | None = None,
    reasoning: str = "medium",
    listener: Callable[[dict[str, Any]], None] | None = None,
    guard: LlamaGuard | None = None,
    options: RunOptions = DEFAULT_OPTIONS,
) -> WorkflowRun:
    """Run the PM -> engineer hand-off. `client` serves the engineer; `pm_client` the PM.

    `budget` limits the whole run, across every role. Raises BindingRefused, before any
    record is written, when a client is not the one its role is bound to. The assignment
    decides the topology; a separate topology needs `orchestrator_client`.
    """
    if workspace.cases is None:
        raise ValueError("the workflow needs registered cases")
    pm = pm_client or client
    assignment.check(pm, client, orchestrator_client)
    orchestrator = orchestrator_client if assignment.topology == "separate" else None
    setup = _Setup(
        question, client, workspace, run_dir, metrics or EarthlabMetrics(),
        budget or Budget(), reasoning, listener, guard, options, assignment, orchestrator,
    )  # fmt: skip
    return _Flow(setup, pm).run()
