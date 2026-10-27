"""Wire one investigation: verified data, tools, verifier, trace, model client, run folder."""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from earthlab.agent.budget import Budget
from earthlab.agent.findings import FindingsLedger, submit_findings_spec
from earthlab.agent.loop import Investigation, Investigator
from earthlab.contracts import SourceSnapshot
from earthlab.data.nea_pm25 import Pm25Dataset, load_pm25
from earthlab.data.snapshot import open_snapshot
from earthlab.llm.client import ChatClient
from earthlab.metrics import EarthlabMetrics
from earthlab.tools.pm25_tools import Pm25Toolset
from earthlab.tools.registry import ToolRegistry
from earthlab.trace import RunTrace
from earthlab.verify.recompute import IndependentSource
from earthlab.verify.verifier import Verifier

SOURCE_LABEL = "nea-pm25"


@dataclass(frozen=True)
class Workspace:
    snapshot: SourceSnapshot
    dataset: Pm25Dataset
    verifier: Verifier


def open_workspace(data_dir: Path) -> Workspace:
    snapshot, path = open_snapshot(data_dir)
    return Workspace(
        snapshot=snapshot,
        dataset=load_pm25(path, snapshot),
        verifier=Verifier(IndependentSource.from_file(path, snapshot.sha256)),
    )


def build_registry(workspace: Workspace, ledger: FindingsLedger) -> ToolRegistry:
    registry = ToolRegistry()
    Pm25Toolset(workspace.dataset).register(registry)
    registry.register(submit_findings_spec(workspace.verifier, ledger))
    return registry


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
) -> Investigation:
    ledger = FindingsLedger()
    registry = build_registry(workspace, ledger)
    metrics = metrics or EarthlabMetrics(tool_names=set(registry.names()))
    metrics.record_qa(SOURCE_LABEL, workspace.dataset.issue_counts())
    trace = RunTrace(run_dir / "trace.jsonl", listener)
    trace.append("source", "runtime", **workspace.snapshot.citation())
    investigator = Investigator(
        client, registry, ledger, metrics=metrics, trace=trace, budget=budget, reasoning=reasoning
    )
    result = investigator.run(question)
    save_result(run_dir, question, result, workspace.snapshot)
    return result


def result_payload(
    question: str, result: Investigation, snapshot: SourceSnapshot
) -> dict[str, Any]:
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
        "seconds": result.seconds,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "estimated_cost_usd": result.cost_usd,
        "source": snapshot.citation(),
        "attribution": snapshot.attribution,
        "answer_audit": None
        if result.answer_audit is None
        else {
            "numbers_checked": result.answer_audit.numbers_checked,
            "ungrounded": list(result.answer_audit.ungrounded),
        },
        "rounds": [[r.model_dump(mode="json") for r in rnd] for rnd in result.ledger.rounds],
    }


def save_result(
    run_dir: Path, question: str, result: Investigation, snapshot: SourceSnapshot
) -> Path:
    path = run_dir / "result.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result_payload(question, result, snapshot), indent=2), "utf-8")
    tmp.replace(path)
    return path
