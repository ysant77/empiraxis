"""Run ScienceBench arms over the ready scenarios and write results.jsonl and summary.json.

Arm A is the rule-based dispatcher; arm B is the single Meta agent. Both get the same
workspace, tools and data. Each row carries run metadata so a reader can reproduce it:
code revision, data and case-file hashes, provider, budget and repeat index.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from earthlab.agent.budget import Budget
from earthlab.bench.dispatcher import Dispatcher
from earthlab.bench.heldout import DEV_NOTE
from earthlab.bench.scenarios import Outcome, Scenario, ScenarioScore, score
from earthlab.digest import file_digest
from earthlab.llm.client import ChatClient
from earthlab.runtime import Workspace, investigate
from earthlab.safety.llama_guard import LlamaGuard

ARMS = ("A", "B")
DISPATCHER_NOTE = "Arm A rules were written after reading the visible dev questions."


def _git(git: str, repo: Path, *args: str) -> str:
    """Fixed git arguments only; no user input reaches the command line."""
    done = subprocess.run([git, "-C", str(repo), *args], capture_output=True, text=True, check=True)  # noqa: S603
    return done.stdout.strip()


def _git_revision(repo: Path) -> str:
    git = shutil.which("git")
    if git is None:
        return "unknown"
    try:
        head, dirty = _git(git, repo, "rev-parse", "HEAD"), _git(git, repo, "status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return head + ("-dirty" if dirty else "")


def run_metadata(
    repo: Path,
    workspace: Workspace,
    client: ChatClient | None,
    budget: Budget,
    scenario_file: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cases = sorted((repo / "config" / "cases").glob("*.yaml"))
    return {
        "started_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "code_revision": _git_revision(repo),
        "python": platform.python_version(),
        "data_sha256": workspace.snapshot.sha256,
        "case_files_sha256": {p.name: file_digest(p) for p in cases},
        "provider": client.config.name if client else None,
        "model": client.config.model if client else None,
        "budget": budget.model_dump(),
        "scenario_file": scenario_file,
        "notes": [DISPATCHER_NOTE, scenario_file["note"] if scenario_file else DEV_NOTE],
    }


def agent_outcome(
    scenario: Scenario,
    client: ChatClient,
    workspace: Workspace,
    run_dir: Path,
    budget: Budget,
    guard: LlamaGuard | None,
) -> Outcome:
    result = investigate(
        scenario.question, client, workspace, run_dir, budget=budget, reasoning="low", guard=guard
    )
    return Outcome(
        status=result.status.value,
        supported=result.ledger.supported(),
        area_supported=result.area_ledger.supported(),
        rejected_claims=len(result.ledger.rejected()),
        reason_codes=sorted({c for entry in result.limitations for c in entry.reasons}),
        answer_issues=list(result.answer_issues),
        seconds=result.seconds,
        turns=result.turns,
        tool_calls=result.tool_calls,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        detail={"run_dir": str(run_dir), "stop_reason": result.stop_reason},
    )


def summarize(scores: list[ScenarioScore], blocked: list[Scenario]) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    for arm in sorted({s.arm for s in scores}):
        rows = [s for s in scores if s.arm == arm]
        arms[arm] = {
            "runs": len(rows),
            "passed": sum(s.passed for s in rows),
            "false_verified": sum(s.false_verified for s in rows),
            "per_scenario": {
                sid: f"{sum(s.passed for s in rows if s.scenario_id == sid)}/"
                f"{sum(1 for s in rows if s.scenario_id == sid)}"
                for sid in sorted({s.scenario_id for s in rows})
            },
        }
    return {"arms": arms, "blocked_unrun": {s.id: s.blocked_reason for s in blocked}}


def run_bench(
    scenarios: list[Scenario],
    arms: list[str],
    workspace: Workspace,
    out_dir: Path,
    *,
    repo: Path,
    client: ChatClient | None = None,
    guard: LlamaGuard | None = None,
    budget: Budget | None = None,
    repeats: int = 1,
    on_score: Callable[[ScenarioScore], None] | None = None,
    scenario_file: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score ready scenarios only; blocked scenarios are reported, never run or scored."""
    unknown = set(arms) - set(ARMS)
    if unknown or ("B" in arms and client is None):
        raise ValueError(f"unknown arms {sorted(unknown)} or arm B without a model client")
    budget = budget or Budget()
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = run_metadata(repo, workspace, client, budget, scenario_file)
    ready = [s for s in scenarios if s.status == "ready"]
    scores: list[ScenarioScore] = []
    with (out_dir / "results.jsonl").open("a", encoding="utf-8") as log:
        for repeat in range(repeats):
            for scenario in ready:
                for arm in arms:
                    if arm == "A":
                        outcome = Dispatcher(workspace).run(scenario.question)
                    else:
                        assert client is not None
                        run_dir = out_dir / "runs" / f"{scenario.id}-r{repeat}"
                        run_dir.mkdir(parents=True, exist_ok=True)
                        outcome = agent_outcome(scenario, client, workspace, run_dir, budget, guard)
                    result = score(scenario, arm, repeat, outcome)
                    scores.append(result)
                    row = {
                        **result.model_dump(mode="json"),
                        "outcome": outcome.model_dump(mode="json"),
                    }
                    log.write(json.dumps({**row, "meta": meta}, default=str) + "\n")
                    log.flush()
                    if on_score is not None:
                        on_score(result)
    summary = {"meta": meta, **summarize(scores, [s for s in scenarios if s.status != "ready"])}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), "utf-8")
    return summary
