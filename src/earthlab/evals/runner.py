"""Run evaluation arms over fixed tasks and write runs.jsonl plus summary.json."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from earthlab.agent.budget import Budget
from earthlab.evals.arms import ArmOutcome, agent_arm, no_tool_arm, scripted_arm
from earthlab.evals.tasks import EvalTask, TaskScore, score
from earthlab.hashing import content_hash
from earthlab.llm.client import ChatClient
from earthlab.runtime import Workspace

ARMS = ("agent", "no_tools", "scripted")


def _run_arm(
    arm: str,
    task: EvalTask,
    client: ChatClient | None,
    workspace: Workspace,
    out_dir: Path,
    budget: Budget,
) -> ArmOutcome:
    if arm == "scripted":
        return scripted_arm(task, workspace)
    if client is None:
        raise ValueError(f"arm {arm} needs a model client")
    if arm == "no_tools":
        return no_tool_arm(task, client, workspace)
    run_dir = out_dir / "agent-runs" / task.id
    run_dir.mkdir(parents=True, exist_ok=True)
    return agent_arm(task, client, workspace, run_dir, budget)


def summarize_scores(scores: list[TaskScore]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for arm in sorted({s.arm for s in scores}):
        rows = [s for s in scores if s.arm == arm]
        summary[arm] = {
            "tasks": len(rows),
            "verified_success": sum(s.verified_success for s in rows),
            "requirements_met": f"{sum(s.met for s in rows)}/{sum(s.required for s in rows)}",
            "rejected_claims": sum(s.rejected_claims for s in rows),
        }
    return summary


def run_suite(
    tasks: list[EvalTask],
    arms: list[str],
    workspace: Workspace,
    out_dir: Path,
    client: ChatClient | None = None,
    budget: Budget | None = None,
    on_score: Callable[[TaskScore], None] | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scores: list[TaskScore] = []
    with (out_dir / "runs.jsonl").open("a", encoding="utf-8") as log:
        for task in tasks:
            for arm in arms:
                outcome = _run_arm(arm, task, client, workspace, out_dir, budget or Budget())
                result = score(task, arm, outcome.final, outcome.rejected_total)
                scores.append(result)
                row = {
                    **result.model_dump(),
                    "seconds": outcome.seconds,
                    "detail": outcome.detail,
                    "question_hash": content_hash(task.question),
                    "provider": client.config.name if client and arm != "scripted" else None,
                    "verdicts": [r.verdict.value for r in outcome.final],
                }
                log.write(json.dumps(row) + "\n")
                log.flush()
                if on_score is not None:
                    on_score(result)
    summary = {
        "n_tasks": len(tasks),
        "arms": summarize_scores(scores),
        "source_sha256": workspace.snapshot.sha256,
        "note": "Smoke evaluation; small samples are descriptive only.",
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
