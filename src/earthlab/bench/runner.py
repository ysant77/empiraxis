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
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from earthlab.agent.budget import Budget
from earthlab.bench.dispatcher import Dispatcher
from earthlab.bench.heldout import DEV_NOTE, HeldoutError
from earthlab.bench.metrics import (
    COST_NOTE,
    INTERVENTIONS_NOTE,
    Row,
    config_hashes,
    summarize,
    trace_counts,
)
from earthlab.bench.runtime_info import guard_record, planner_record, probe_failures
from earthlab.bench.scenarios import Outcome, Scenario, ScenarioScore, score
from earthlab.digest import file_digest
from earthlab.llm.client import ChatClient
from earthlab.runtime import DEFAULT_OPTIONS, RunOptions, Workspace, investigate
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
    reasoning: str = "low",
    guard: LlamaGuard | None = None,
) -> dict[str, Any]:
    cases = sorted((repo / "config" / "cases").glob("*.yaml"))
    return {
        "started_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "code_revision": _git_revision(repo),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "config_sha256": config_hashes(repo),
        "data_sha256": workspace.snapshot.sha256,
        "case_files_sha256": {p.name: file_digest(p) for p in cases},
        "provider": client.config.name if client else None,
        "model": client.config.model if client else None,
        "price_source": client.config.price_source if client else None,
        "planner": planner_record(client.config, budget.max_output_tokens) if client else None,
        "reasoning_prompt": reasoning,
        "guard": guard_record(guard),
        "budget": budget.model_dump(),
        "scenario_file": scenario_file,
        "notes": [
            DISPATCHER_NOTE,
            scenario_file["note"] if scenario_file else DEV_NOTE,
            INTERVENTIONS_NOTE,
            COST_NOTE,
        ],
    }


def check_official(meta: dict[str, Any]) -> None:
    """A held-out run is official: it needs a clean commit and readable server settings."""
    revision = meta["code_revision"]
    if revision == "unknown" or revision.endswith("-dirty"):
        raise HeldoutError(f"a held-out run needs a clean git revision, got {revision}")
    failed = probe_failures(meta["planner"], meta["guard"])
    if failed:
        raise HeldoutError(f"a held-out run needs server settings from: {', '.join(failed)}")


def agent_outcome(
    scenario: Scenario,
    client: ChatClient,
    workspace: Workspace,
    run_dir: Path,
    budget: Budget,
    guard: LlamaGuard | None,
    reasoning: str = "low",
    options: RunOptions = DEFAULT_OPTIONS,
) -> Outcome:
    result = investigate(
        scenario.question,
        client,
        workspace,
        run_dir,
        budget=budget,
        reasoning=reasoning,
        guard=guard,
        options=options,
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
        **trace_counts(run_dir),
        guard_blocks=sum(not d.allowed for d in result.safety),
        cost_usd=result.cost_usd,
        detail={
            "run_dir": str(run_dir),
            "stop_reason": result.stop_reason,
            "plan_verdicts": [r.verdict for r in result.plan_reviews],
            "answer_source": result.answer_source,
        },
    )


def _guarded_outcome(
    arm: str,
    scenario: Scenario,
    repeat: int,
    workspace: Workspace,
    out_dir: Path,
    client: ChatClient | None,
    budget: Budget,
    guard: LlamaGuard | None,
    reasoning: str,
    options: RunOptions = DEFAULT_OPTIONS,
) -> Outcome:
    """One arm on one scenario. An unexpected exception becomes an 'error' outcome, which
    scores as a failure, so a crash never removes a row from the denominator. The bench
    clock times every row, so a failure never shows as faster than it was."""
    started = time.monotonic()
    try:
        if arm == "A":
            outcome = Dispatcher(workspace).run(scenario.question)
        else:
            assert client is not None
            run_dir = out_dir / "runs" / f"{scenario.id}-r{repeat}"
            run_dir.mkdir(parents=True, exist_ok=True)
            outcome = agent_outcome(
                scenario,
                client,
                workspace,
                run_dir,
                budget,
                guard,
                reasoning,
                options,
            )
    except Exception as exc:  # recorded as a failed row, never hidden
        error = f"{type(exc).__name__}: {exc}"
        outcome = Outcome(status="error", seconds=0.0, cost_usd=None, detail={"error": error})
    return outcome.model_copy(update={"seconds": round(time.monotonic() - started, 3)})


def _check_arms(arms: list[str], client: ChatClient | None) -> None:
    unknown = set(arms) - set(ARMS)
    if unknown or ("B" in arms and client is None):
        raise ValueError(f"unknown arms {sorted(unknown)} or arm B without a model client")


def _write_row(log: IO[str], result: ScenarioScore, outcome: Outcome, meta: dict[str, Any]) -> None:
    row = {**result.model_dump(mode="json"), "outcome": outcome.model_dump(mode="json")}
    log.write(json.dumps({**row, "meta": meta}, default=str) + "\n")
    log.flush()


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
    reasoning: str = "low",
    before_rows: Callable[[dict[str, Any]], None] | None = None,
    options: RunOptions = DEFAULT_OPTIONS,
) -> dict[str, Any]:
    """Score ready scenarios only; blocked ones are reported. before_rows can refuse a run."""
    _check_arms(arms, client)
    budget = budget or Budget()
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = run_metadata(repo, workspace, client, budget, scenario_file, reasoning, guard)
    meta |= {"arms": arms, "repeats": repeats, "options": asdict(options)}
    if scenario_file and scenario_file["heldout"]:
        check_official(meta)
    if before_rows is not None:
        before_rows(meta)
    ready = [s for s in scenarios if s.status == "ready"]
    rows: list[Row] = []
    with (out_dir / "results.jsonl").open("a", encoding="utf-8") as log:
        for repeat in range(repeats):
            for scenario in ready:
                for arm in arms:
                    ctx = (workspace, out_dir, client, budget, guard, reasoning, options)
                    outcome = _guarded_outcome(arm, scenario, repeat, *ctx)
                    result = score(scenario, arm, repeat, outcome)
                    rows.append((scenario, result, outcome))
                    _write_row(log, result, outcome, meta)
                    if on_score is not None:
                        on_score(result)
    expected = len(ready) * len(arms) * repeats
    summary = {
        "meta": meta,
        "rows_expected": expected,
        "rows_written": len(rows),
        "complete": len(rows) == expected,
        **summarize(rows, [s for s in scenarios if s.status != "ready"]),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), "utf-8")
    return summary
