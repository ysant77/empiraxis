"""One research request through the product manager and the Geospatial Engineer.

The Python controller here owns every transition, permission and limit:

received -> safety gate -> PM brief (one model call, one correction) -> brief validated
-> needs_input | out_of_scope | engineering task -> engineer run (the existing plan-
reviewed investigator, limited to the assigned case) -> verified result to the PM -> PM
report (audited; else the engineer's audited answer) -> finished.

The product manager has one schema-only tool and never sees a scientific tool. The
engineer is the existing investigator with plan review on. Both trace into one hash chain.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from earthlab.agent.budget import Budget, BudgetMeter, BudgetStop, prompt_bytes
from earthlab.agent.loop import PLANNER_TEMPERATURE, Investigation, RunStatus
from earthlab.cases.tools import CaseLibrary
from earthlab.digest import payload_digest
from earthlab.llm.client import ChatClient
from earthlab.llm.types import ChatResponse, ProviderError, Usage
from earthlab.metrics import EarthlabMetrics
from earthlab.runtime import (
    DEFAULT_OPTIONS,
    RunOptions,
    Workspace,
    investigate,
    result_payload,
)
from earthlab.safety.gate import SafetyGate
from earthlab.safety.llama_guard import LlamaGuard
from earthlab.tools.registry import ToolSpec
from earthlab.trace import RunTrace
from earthlab.verify.answer_audit import audit_answer
from earthlab.verify.claims import Verdict
from earthlab.workflow.contracts import (
    BriefProposal,
    EngineeringReplyV1,
    EngineeringTaskV1,
    ManagerResultV1,
    ProductBriefV1,
    RoleCall,
    WorkflowStatus,
)
from earthlab.workflow.prompts import PM_REPORT, PM_SYSTEM, case_catalogue, engineer_prompt

SUBMIT_BRIEF = "submit_brief"
PM_CALLS = 2  # the brief and one correction
PM_REPORT_CALLS = 1
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_UNIT_NAMES = re.compile(r"PM2\.5|PM10|ug/m3|µg/m³", re.IGNORECASE)  # names, not figures
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


def _brief_spec() -> ToolSpec:
    return ToolSpec(
        SUBMIT_BRIEF,
        "Submit the structured research brief. This is your only tool.",
        BriefProposal,
        lambda _: {},
    )


def _numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(_UNIT_NAMES.sub(" ", text)))


def validate_brief(proposal: BriefProposal, request: str, cases: CaseLibrary) -> list[str]:
    """Why the brief cannot be forwarded; empty when it can. Same inputs, same answer."""
    issues: list[str] = []
    known = set(cases.ids())
    if proposal.case_id is not None and proposal.case_id not in known:
        issues.append(
            f"case {proposal.case_id} is not registered; known: {', '.join(sorted(known))}"
        )
    if proposal.route == "engineer" and proposal.case_id is None:
        issues.append("route engineer needs a registered case_id")
    if proposal.route == "engineer" and proposal.clarifications_needed:
        issues.append("route engineer cannot carry open clarifications; use needs_input")
    if proposal.route == "needs_input" and not proposal.clarifications_needed:
        issues.append("route needs_input must list the clarifications needed")
    if (proposal.period_start is None) != (proposal.period_end is None):
        issues.append("give both period_start and period_end, or neither")
    case_text = ""
    if proposal.case_id in known:
        case = cases.get(str(proposal.case_id)).case
        case_text = f"{case.title} {case.question}"
        if proposal.period_start is not None and proposal.period_end is not None:
            if proposal.period_start >= proposal.period_end:
                issues.append("period_start must be before period_end")
            elif proposal.period_start < case.period.start or proposal.period_end > case.period.end:
                issues.append(
                    f"period is outside the case period {case.period.start.date()} to "
                    f"{case.period.end.date()}"
                )
    # A product manager restates the request; it never adds a figure of its own.
    written = " ".join(
        [
            proposal.normalized_question,
            proposal.target_quantity or "",
            *proposal.constraints,
            *proposal.clarifications_needed,
        ]
    )
    invented = sorted(_numbers(written) - _numbers(f"{request} {case_text}"))
    if invented:
        issues.append(f"numbers not in the request or the case: {', '.join(invented)}")
    return issues


class _Roles:
    """Model calls for the product manager, metered and traced like the investigator's."""

    def __init__(self, client: ChatClient, trace: RunTrace, metrics: EarthlabMetrics):
        self.client = client
        self.trace = trace
        self.metrics = metrics
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.served_model: str | None = None

    def call(
        self,
        meter: BudgetMeter,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str,
    ) -> ChatResponse:
        cfg = self.client.config
        worst = meter.reserve_model_call(cfg, prompt_bytes(messages, tools))
        self.calls += 1
        try:
            resp = self.client.chat(
                messages,
                tools,
                max_tokens=meter.budget.max_output_tokens,
                temperature=PLANNER_TEMPERATURE,
                tool_choice=tool_choice,
                timeout=min(cfg.timeout_seconds, meter.remaining_seconds()),
            )
        except ProviderError as exc:
            meter.settle_model_call(cfg, Usage(), worst)  # a failed call may still be billed
            self.metrics.record_inference(cfg.name, cfg.logical_model, exc.kind.value, None)
            self.trace.append(
                "model_error",
                "runtime",
                kind=exc.kind.value,
                attempt=1,
                max_attempts=1,
                retrying=False,
                role="product_manager",
            )
            raise
        meter.settle_model_call(cfg, resp.usage, worst)
        self.prompt_tokens += resp.usage.prompt_tokens or 0
        self.completion_tokens += resp.usage.completion_tokens or 0
        self.served_model = resp.served_model or self.served_model
        self.metrics.record_inference(
            cfg.name,
            cfg.logical_model,
            "ok",
            resp.wall_seconds,
            (resp.usage.prompt_tokens, resp.usage.completion_tokens),
            cfg.estimate_cost_usd(resp.usage.prompt_tokens, resp.usage.completion_tokens),
        )
        self.trace.append(
            "model_turn",
            "model",
            role="product_manager",
            turn=self.calls,
            request_id=resp.request_id,
            served_model=resp.served_model,
            content=resp.content,
            reasoning=resp.reasoning,
            tool_calls=[c.model_dump() for c in resp.tool_calls],
            usage=resp.usage.model_dump(),
            wall_seconds=round(resp.wall_seconds, 3),
        )
        return resp

    def role_call(self, role: str) -> RoleCall:
        cfg = self.client.config
        return RoleCall.model_validate(
            {
                "role_id": role,
                "provider": cfg.name,
                "model": cfg.model,
                "logical_model": cfg.logical_model,
                "served_model": self.served_model,
            }
        )


def _pm_budget(budget: Budget, calls: int) -> Budget:
    """The run's limits, with the PM's own call count."""
    return budget.model_copy(update={"max_turns": calls})


def _propose_brief(
    roles: _Roles, question: str, cases: CaseLibrary, budget: Budget, task_id: str
) -> tuple[ProductBriefV1 | None, list[str]]:
    """The PM's brief once it passes validation, or None with the last issues."""
    spec = _brief_spec()
    meter = BudgetMeter(_pm_budget(budget, PM_CALLS))
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": PM_SYSTEM.format(cases=case_catalogue(cases))},
        {"role": "user", "content": question},
    ]
    issues = ["no brief was submitted"]
    for _ in range(PM_CALLS):
        resp = roles.call(meter, messages, [spec.schema()], "auto")
        messages.append(_assistant(resp))
        calls = [c for c in resp.tool_calls if c.name == SUBMIT_BRIEF]
        proposal: BriefProposal | None = None
        if not calls:
            issues = ["no brief was submitted; call submit_brief"]
        else:
            try:
                proposal = BriefProposal.model_validate_json(calls[0].arguments)
                issues = validate_brief(proposal, question, cases)
            except ValidationError as exc:
                issues = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()][:6]
        brief = None
        if proposal is not None and not issues:
            brief = ProductBriefV1(
                task_id=task_id,
                request_sha256=payload_digest(question),
                brief=proposal,
                author=roles.role_call("product_manager"),
            )
        roles.trace.append(
            "brief_reviewed",
            "runtime",
            task_id=task_id,
            valid=brief is not None,
            issues=issues,
            route=None if proposal is None else proposal.route,
            brief_sha256=None if brief is None else payload_digest(brief.model_dump(mode="json")),
            brief=None if brief is None else brief.model_dump(mode="json"),
        )
        if brief is not None:
            return brief, []
        for call in resp.tool_calls:
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps({"issues": issues})}
            )
        if not resp.tool_calls:
            messages.append({"role": "user", "content": "Fix: " + "; ".join(issues)})
    return None, issues


def _assistant(resp: ChatResponse) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": resp.content}
    if resp.tool_calls:
        message["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in resp.tool_calls
        ]
    return message


def engineering_task(
    brief: ProductBriefV1, cases: CaseLibrary, budget: Budget
) -> EngineeringTaskV1:
    case_file = cases.get(str(brief.brief.case_id))
    return EngineeringTaskV1(
        task_id=f"{brief.task_id}.ge",
        parent_task_id=brief.task_id,
        brief_sha256=payload_digest(brief.model_dump(mode="json")),
        objective=brief.brief.normalized_question,
        case_id=case_file.case.case_id,
        allowed_dataset_ids=tuple(sorted(case_file.assets)),
        allowed_method_ids=(case_file.case.method_id,),
        max_model_calls=budget.max_turns,
        max_tool_calls=budget.max_tool_calls,
        max_seconds=budget.max_seconds,
        max_cost_usd=budget.max_usd,
    )


def _only(cases: CaseLibrary, case_id: str) -> CaseLibrary:
    """A library holding one case, so the engineer cannot plan or claim outside it."""
    files = {case_id: cases.files[case_id]} if case_id in cases.files else {}
    return CaseLibrary({case_id: cases.get(case_id)}, cases.root, files)


def _reply(task: EngineeringTaskV1, result: Investigation, ms: int, author: RoleCall) -> Any:
    area_ok = [
        i for i, r in result.area_ledger.latest_by_id().items() if r.verdict is Verdict.SUPPORTED
    ]
    pm25_ok = [i for i, r in result.ledger.latest_by_id().items() if r.verdict is Verdict.SUPPORTED]
    return EngineeringReplyV1(
        task_id=task.task_id,
        status=result.status.value,
        plan_sha256=tuple(r.plan_sha256 for r in result.plan_reviews),
        critic_verdicts=tuple(r.verdict for r in result.plan_reviews),
        supported_finding_ids=tuple(sorted(pm25_ok + area_ok)),
        limitation_reasons=tuple(
            sorted({c.value for entry in result.limitations for c in entry.reasons})
        ),
        elapsed_ms=ms,
        author=author,
    )


def _pm_report(
    roles: _Roles,
    gate: SafetyGate,
    question: str,
    reply: EngineeringReplyV1,
    result: Investigation,
    budget: Budget,
) -> tuple[str, str]:
    """The PM's report and its source. Falls back to the engineer's audited answer.

    Only verified, partial and abstained runs have an answer that passed the audit and
    the safety gate; any other outcome reports no text.
    """
    if result.status not in _REPORTABLE or not result.answer:
        return ("none", "")
    fallback = ("rendered" if result.answer_source == "rendered" else "engineer", result.answer)
    envelope = {
        "status": reply.status,
        "verified_finding_ids": list(reply.supported_finding_ids),
        "limitations": list(reply.limitation_reasons),
        "engineer_answer": result.answer,
    }
    messages = [
        {"role": "system", "content": PM_REPORT},
        {"role": "user", "content": json.dumps(envelope)},
    ]
    try:
        resp = roles.call(BudgetMeter(_pm_budget(budget, PM_REPORT_CALLS)), messages, [], "none")
    except (ProviderError, BudgetStop) as exc:
        roles.trace.append(
            "pm_report", "runtime", passed=False, issues=[str(exc)], source=fallback[0]
        )
        return fallback
    text = resp.content.strip()
    area_ok = {
        i for i, r in result.area_ledger.latest_by_id().items() if r.verdict is Verdict.SUPPORTED
    }
    audit = audit_answer(text, result.ledger.latest_by_id(), area_ok)
    issues = audit.problems() if text else ["the report is empty"]
    if not issues:
        decision = gate.check_answer(question, text)
        issues = [] if decision.allowed else [f"safety gate: {decision.reason}"]
    source = "pm_model" if not issues else fallback[0]
    roles.trace.append("pm_report", "runtime", passed=not issues, issues=issues, source=source)
    return (source, text) if not issues else fallback


def run_workflow(
    question: str,
    client: ChatClient,
    workspace: Workspace,
    run_dir: Path,
    *,
    pm_client: ChatClient | None = None,
    metrics: EarthlabMetrics | None = None,
    budget: Budget | None = None,
    reasoning: str = "medium",
    listener: Callable[[dict[str, Any]], None] | None = None,
    guard: LlamaGuard | None = None,
    options: RunOptions = DEFAULT_OPTIONS,
) -> WorkflowRun:
    """Run the PM -> engineer hand-off. `client` serves the engineer; `pm_client` the PM."""
    if workspace.cases is None:
        raise ValueError("the workflow needs registered cases")
    budget = budget or Budget()
    metrics = metrics or EarthlabMetrics()
    pm = pm_client or client
    trace = RunTrace(run_dir / "trace.jsonl", listener)
    task_id = re.sub(r"[^a-z0-9._-]", "-", run_dir.name.lower()).lstrip("-._") or "run"
    trace.append(
        "workflow_start",
        "runtime",
        question=question,
        task_id=task_id,
        topology="combined",
        pm={"provider": pm.config.name, "model": pm.config.model},
        engineer={"provider": client.config.name, "model": client.config.model},
    )
    roles = _Roles(pm, trace, metrics)
    gate = SafetyGate(guard, metrics, trace)
    asked = gate.check_question(question)
    if not asked.allowed or asked.causal_only():
        # Refusals and causal abstentions never reach a model; the existing path records them.
        result = investigate(question, client, workspace, run_dir, metrics=metrics, guard=guard)
        trace.resync()
        manager = ManagerResultV1(
            task_id=task_id,
            status=result.status.value,
            report_text=result.answer,
            report_source="engineer" if result.answer else "none",
        )
        return _finish(
            trace, run_dir, question, workspace, None, None, None, manager, result, roles
        )

    trace.append(
        "role_invocation", "runtime", phase="started", role="product_manager", task_id=task_id
    )
    try:
        brief, issues = _propose_brief(roles, question, workspace.cases, budget, task_id)
        pm_status = "completed" if brief is not None else "failed"
    except (ProviderError, BudgetStop) as exc:
        brief, issues, pm_status = None, [str(exc)], "failed"
    trace.append(
        "role_invocation",
        "runtime",
        phase="finished",
        role="product_manager",
        task_id=task_id,
        status=pm_status,
        model_calls=roles.calls,
    )
    if brief is None:
        manager = ManagerResultV1(task_id=task_id, status="failed", typed_limitations=tuple(issues))
        return _finish(trace, run_dir, question, workspace, None, None, None, manager, None, roles)
    if brief.brief.route != "engineer":
        manager = ManagerResultV1(
            task_id=task_id,
            status=brief.brief.route,
            followup_questions=brief.brief.clarifications_needed,
        )
        return _finish(trace, run_dir, question, workspace, brief, None, None, manager, None, roles)

    task = engineering_task(brief, workspace.cases, budget)
    trace.append(
        "task_handoff",
        "runtime",
        task_id=task.task_id,
        parent_task_id=task.parent_task_id,
        receiver="geospatial_engineer",
        brief_sha256=task.brief_sha256,
        task_sha256=payload_digest(task.model_dump(mode="json")),
        task=task.model_dump(mode="json"),
    )
    trace.append(
        "role_invocation",
        "runtime",
        phase="started",
        role="geospatial_engineer",
        task_id=task.task_id,
    )
    started = time.perf_counter()
    engineer_space = replace(workspace, cases=_only(workspace.cases, task.case_id))
    result = investigate(
        engineer_prompt(task, brief, question),
        client,
        engineer_space,
        run_dir,
        metrics=metrics,
        budget=budget,
        reasoning=reasoning,
        listener=listener,
        guard=guard,
        options=replace(options, plan_review=True),
    )
    trace.resync()  # investigate appended to the same file through its own handle
    ms = round((time.perf_counter() - started) * 1000)
    author = RoleCall.model_validate(
        {
            "role_id": "geospatial_engineer",
            "provider": client.config.name,
            "model": client.config.model,
            "logical_model": client.config.logical_model,
            "served_model": result.served_model,
        }
    )
    reply = _reply(task, result, ms, author)
    trace.append(
        "role_invocation",
        "runtime",
        phase="finished",
        role="geospatial_engineer",
        task_id=task.task_id,
        status=reply.status,
        model_calls=result.turns,
    )
    trace.append(
        "result_delivered",
        "runtime",
        task_id=task.task_id,
        receiver="product_manager",
        reply_sha256=payload_digest(reply.model_dump(mode="json")),
        reply=reply.model_dump(mode="json"),
    )
    source, text = _pm_report(roles, gate, question, reply, result, budget)
    manager = ManagerResultV1(
        task_id=task_id,
        status=reply.status,
        verified_finding_refs=reply.supported_finding_ids,
        typed_limitations=reply.limitation_reasons,
        report_text=text,
        report_source=source,
        source_hashes=(workspace.snapshot.sha256,),
    )
    return _finish(trace, run_dir, question, workspace, brief, task, reply, manager, result, roles)


def _finish(
    trace: RunTrace,
    run_dir: Path,
    question: str,
    workspace: Workspace,
    brief: ProductBriefV1 | None,
    task: EngineeringTaskV1 | None,
    reply: EngineeringReplyV1 | None,
    manager: ManagerResultV1,
    result: Investigation | None,
    roles: _Roles,
) -> WorkflowRun:
    trace.append(
        "finish",
        "runtime",
        status=manager.status,
        reason=f"workflow {manager.status}",
        workflow=True,
        turns=roles.calls + (result.turns if result else 0),
        report_source=manager.report_source,
    )
    block = {
        "topology": "combined",
        "pm_calls": roles.calls,
        "pm_prompt_tokens": roles.prompt_tokens,
        "pm_completion_tokens": roles.completion_tokens,
        "brief": None if brief is None else brief.model_dump(mode="json"),
        "engineering_task": None if task is None else task.model_dump(mode="json"),
        "engineering_reply": None if reply is None else reply.model_dump(mode="json"),
        "manager_result": manager.model_dump(mode="json"),
    }
    if result is not None:
        payload = result_payload(question, result, workspace.snapshot, workspace.cases)
    else:
        payload = {"question": question, "source": workspace.snapshot.citation()}
    payload |= {"status": manager.status, "workflow": block}
    path = run_dir / "result.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), "utf-8")
    tmp.replace(path)
    return WorkflowRun(manager.status, brief, task, reply, manager, result, roles.calls)
