"""Wire one investigation: verified data, tools, verifier, trace, model client, run folder."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from earthlab.acquire.gate import load_approvals
from earthlab.agent.area_findings import AreaLedger, submit_area_findings_spec
from earthlab.agent.budget import Budget
from earthlab.agent.findings import FindingsLedger, submit_findings_spec
from earthlab.agent.limitations import (
    LimitationArgs,
    LimitationLog,
    ReasonCode,
    declare_limitation_spec,
)
from earthlab.agent.loop import Investigation, Investigator, RunStatus
from earthlab.agent.plan_step import PlanStep
from earthlab.agent.rendered import verified_block
from earthlab.cases.tools import CaseLibrary, assess_case_spec
from earthlab.contracts import SourceSnapshot
from earthlab.data.nea_pm25 import Pm25Dataset, load_pm25
from earthlab.data.snapshot import open_snapshot
from earthlab.llm.client import ChatClient
from earthlab.llm.retry import NO_RETRY, RetryPolicy
from earthlab.metrics import EarthlabMetrics
from earthlab.planning.registry import Registry, load_registry
from earthlab.report.evidence import collect_evidence
from earthlab.safety.gate import CAUSAL_ABSTENTION, REFUSAL, SafetyDecision, SafetyGate
from earthlab.safety.llama_guard import LlamaGuard
from earthlab.tools.burned_area_tools import burned_area_spec
from earthlab.tools.pm25_tools import Pm25Toolset
from earthlab.tools.registry import ToolRegistry
from earthlab.trace import RunTrace
from earthlab.verify.recompute import IndependentSource
from earthlab.verify.verifier import Verifier

SOURCE_LABEL = "nea-pm25"
APPROVALS_DIR = Path("config") / "approvals"


@dataclass(frozen=True)
class TaskScope:
    """What one assigned task may touch. The model sees and can call only these tools,
    and its plan may name only these datasets. None on RunOptions means no task limit."""

    tools: frozenset[str]
    dataset_ids: frozenset[str]


@dataclass(frozen=True)
class RunOptions:
    """Steps added after the frozen v1 protocol. Both are off unless a caller asks.

    plan_review: the model submits a typed plan that the deterministic critic reviews.
    render_fallback: a text that fails the answer audit after its revision is replaced by
    an answer rendered from verified findings only.
    provider_retry: one more attempt after a transient provider failure. None keeps the
    v1 protocol: one attempt per model call.
    scope: the tools and datasets an assigned task may use (the workflow engineer).
    """

    plan_review: bool = False
    render_fallback: bool = False
    provider_retry: RetryPolicy | None = None
    scope: TaskScope | None = None


DEFAULT_OPTIONS = RunOptions()


@dataclass(frozen=True)
class Workspace:
    snapshot: SourceSnapshot
    dataset: Pm25Dataset
    verifier: Verifier
    cases: CaseLibrary | None = None


def open_workspace(data_dir: Path, cases_dir: Path | None = None) -> Workspace:
    """Open the pinned NEA data and, when present, the case files in config/cases.

    The default case folder sits two levels above the data folder (repo/data/nea ->
    repo/config/cases); manifest paths in case files are relative to that repo root.
    """
    snapshot, path = open_snapshot(data_dir)
    root = data_dir.resolve().parents[1]
    cases_dir = cases_dir or root / "config" / "cases"
    cases = (
        CaseLibrary.load(cases_dir, cases_dir.resolve().parents[1]) if cases_dir.is_dir() else None
    )
    return Workspace(
        snapshot=snapshot,
        dataset=load_pm25(path, snapshot),
        verifier=Verifier(IndependentSource.from_file(path, snapshot.sha256)),
        cases=cases,
    )


def build_registry(
    workspace: Workspace,
    ledger: FindingsLedger,
    limitations: LimitationLog | None = None,
    area_ledger: AreaLedger | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    Pm25Toolset(workspace.dataset).register(registry)
    registry.register(submit_findings_spec(workspace.verifier, ledger))
    registry.register(declare_limitation_spec(limitations or LimitationLog()))
    if workspace.cases is not None:
        area_ledger = area_ledger or AreaLedger()
        registry.register(assess_case_spec(workspace.cases))
        registry.register(burned_area_spec(workspace.cases, area_ledger.consulted))
        registry.register(submit_area_findings_spec(workspace.cases, area_ledger))
    return registry


def plan_step_for(
    workspace: Workspace, trace: RunTrace, run_dir: Path, scope: TaskScope | None = None
) -> PlanStep | None:
    """The plan step for a run with registered cases; None when there are no cases.

    With a scope, the critic's registry holds only the scope's datasets, so a plan that
    names any other dataset is refused as unregistered.
    """
    if workspace.cases is None:
        return None
    root = workspace.cases.root
    registry = load_registry(root)
    if scope is not None:
        registry = Registry(
            candidates={k: v for k, v in registry.candidates.items() if k in scope.dataset_ids},
            assets=registry.assets,
        )
    folder = root / APPROVALS_DIR
    task_id = re.sub(r"[^a-z0-9._-]", "-", run_dir.name.lower()).lstrip("-._") or "run"
    return PlanStep(
        cases=workspace.cases,
        registry=registry,
        approvals=load_approvals(folder) if folder.is_dir() else [],
        trace=trace,
        task_id=task_id,
    )


def new_run_dir(root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"{stamp}-{secrets.token_hex(3)}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def investigate(
    question: str,
    client: ChatClient,
    workspace: Workspace,
    run_dir: Path,
    *,
    metrics: EarthlabMetrics | None = None,
    budget: Budget | None = None,
    reasoning: str = "medium",
    listener: Callable[[dict[str, Any]], None] | None = None,
    guard: LlamaGuard | None = None,
    options: RunOptions = DEFAULT_OPTIONS,
) -> Investigation:
    """Gate the question, run the agent, then gate the final answer before saving."""
    ledger, limitations, area_ledger = FindingsLedger(), LimitationLog(), AreaLedger()
    trace = RunTrace(run_dir / "trace.jsonl", listener)
    registry = build_registry(workspace, ledger, limitations, area_ledger)
    registry, plan_step = _scoped(registry, workspace, trace, run_dir, options)
    metrics = metrics or EarthlabMetrics(tool_names=set(registry.names()))
    metrics.record_qa(SOURCE_LABEL, workspace.dataset.issue_counts())
    trace.append("source", "runtime", **workspace.snapshot.citation())
    gate = SafetyGate(guard, metrics, trace)
    asked = gate.check_question(question)
    if asked.causal_only():
        result = _causal_abstention(client, ledger, asked, metrics, trace)
    elif not asked.allowed:
        result = _refused(client, ledger, asked, metrics, trace)
    else:
        investigator = Investigator(
            client,
            registry,
            ledger,
            metrics=metrics,
            trace=trace,
            budget=budget,
            reasoning=reasoning,
            answer_gate=gate.check_answer,
            limitations=limitations,
            area_ledger=area_ledger,
            plan_step=plan_step,
            render_fallback=options.render_fallback,
            retry=options.provider_retry or NO_RETRY,
        )
        result = investigator.run(question)
        result = replace(result, safety=(asked, *result.safety))
    save_result(run_dir, question, result, workspace.snapshot, workspace.cases)
    return result


def _scoped(
    registry: ToolRegistry, workspace: Workspace, trace: RunTrace, run_dir: Path, opts: RunOptions
) -> tuple[ToolRegistry, PlanStep | None]:
    """Add the plan step when asked, then keep only the scope's tools when one is set."""
    plan_step = plan_step_for(workspace, trace, run_dir, opts.scope) if opts.plan_review else None
    if plan_step is not None:
        registry.register(plan_step.spec())
    return (registry if opts.scope is None else registry.only(opts.scope.tools)), plan_step


def _refused(
    client: ChatClient,
    ledger: FindingsLedger,
    decision: SafetyDecision,
    metrics: EarthlabMetrics,
    trace: RunTrace,
) -> Investigation:
    """A refused question never reaches the planner model."""
    metrics.investigations.labels(RunStatus.REFUSED.value).inc()
    trace.append("finish", "runtime", status=RunStatus.REFUSED.value, reason=decision.reason)
    return _refused_fields(client, ledger, decision)


def _refused_fields(
    client: ChatClient, ledger: FindingsLedger, decision: SafetyDecision
) -> Investigation:
    """The result of a run that stopped at the question gate: no model call was made."""
    return Investigation(
        status=RunStatus.REFUSED,
        stop_reason=decision.reason or "refused",
        answer=REFUSAL,
        ledger=ledger,
        turns=0,
        tool_calls=0,
        submissions=0,
        seconds=0.0,
        cost_usd=client.config.estimate_cost_usd(0, 0),
        provider=client.config.name,
        model=client.config.model,
        served_model=None,
        prompt_tokens=0,
        completion_tokens=0,
        safety=(decision,),
    )


def _causal_abstention(
    client: ChatClient,
    ledger: FindingsLedger,
    decision: SafetyDecision,
    metrics: EarthlabMetrics,
    trace: RunTrace,
) -> Investigation:
    """A question blocked for causal attribution alone becomes a typed abstention.

    The planner model never runs; the abstention is the system's, not the model's.
    """
    limitation = LimitationArgs(
        reasons=[ReasonCode.CAUSATION_NOT_IDENTIFIABLE],
        explanation="Observations alone cannot identify the cause the question asks for.",
    )
    trace.append("forced_abstention", "safety", reasons=["causation_not_identifiable"])
    metrics.investigations.labels(RunStatus.ABSTAINED.value).inc()
    trace.append("finish", "runtime", status=RunStatus.ABSTAINED.value, reason="causal attribution")
    refused = _refused_fields(client, ledger, decision)
    return replace(
        refused,
        status=RunStatus.ABSTAINED,
        stop_reason="causal attribution routed to an abstention",
        answer=CAUSAL_ABSTENTION,
        limitations=(limitation,),
    )


def result_payload(
    question: str,
    result: Investigation,
    snapshot: SourceSnapshot,
    cases: CaseLibrary | None = None,
) -> dict[str, Any]:
    """The saved run. With cases, evidence holds the hash of every burned-area input read."""
    return {
        "question": question,
        "status": result.status.value,
        "stop_reason": result.stop_reason,
        "answer": result.answer,
        "provider": result.provider,
        "model": result.model,
        "served_model": result.served_model,
        "turns": result.turns,
        "tool_calls": result.tool_calls,
        "submissions": result.submissions,
        "skipped_tool_calls": result.skipped_tool_calls,
        "seconds": result.seconds,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "estimated_cost_usd": result.cost_usd,
        "source": snapshot.citation(),
        "attribution": snapshot.attribution,
        "safety": [d.model_dump(mode="json") for d in result.safety],
        "answer_issues": list(result.answer_issues),
        "answer_source": result.answer_source,
        "findings_text": verified_block(result.ledger, result.area_ledger, result.limitations),
        "answer_audit": None
        if result.answer_audit is None
        else result.answer_audit.model_dump(mode="json"),
        "findings": result.ledger.records(snapshot.sha256),
        "limitations": [entry.model_dump(mode="json") for entry in result.limitations],
        "area_findings": result.area_ledger.records(),
        "area_rounds": [
            [r.model_dump(mode="json") for r in rnd] for rnd in result.area_ledger.rounds
        ],
        "rounds": [[r.model_dump(mode="json") for r in rnd] for rnd in result.ledger.rounds],
        "evidence": collect_evidence(cases, result.area_ledger),
        "plan_reviews": [r.model_dump(mode="json") for r in result.plan_reviews],
    }


def save_result(
    run_dir: Path,
    question: str,
    result: Investigation,
    snapshot: SourceSnapshot,
    cases: CaseLibrary | None = None,
) -> Path:
    path = run_dir / "result.json"
    tmp = path.with_suffix(".tmp")
    payload = result_payload(question, result, snapshot, cases)
    tmp.write_text(json.dumps(payload, indent=2), "utf-8")
    tmp.replace(path)
    return path
