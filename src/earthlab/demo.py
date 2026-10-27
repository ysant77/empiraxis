"""The wildfire demonstration: fixed ScienceBench questions, each run by the Meta agent,
reported and replayed offline. The demo shows what happened; it scores nothing.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from earthlab.bench.scenarios import load_scenarios
from earthlab.llm.client import ChatClient
from earthlab.report.write import write_report
from earthlab.runtime import Workspace, investigate, new_run_dir
from earthlab.safety.llama_guard import LlamaGuard
from earthlab.verify.replay import replay_run

SCENARIO_FILE = Path("evals") / "sciencebench_dev_v1.yaml"
# Area, gated month, comparison with a gated month, QA sensitivity, cause, hotspots.
DEMO_IDS = ("SB-05", "SB-05b", "SB-05c", "SB-07", "SB-05d", "SB-06")


def run_demo(
    ids: list[str],
    make_client: Callable[[], ChatClient],
    workspace: Workspace,
    runs_dir: Path,
    data_dir: Path,
    *,
    guard: LlamaGuard | None = None,
    reasoning: str = "low",
) -> list[dict[str, Any]]:
    """Run each question once; write report.md, replay the run, save demo_summary.json."""
    root = workspace.cases.root if workspace.cases is not None else Path.cwd()
    scenarios = {s.id: s for s in load_scenarios(root / SCENARIO_FILE)}
    unknown = [i for i in ids if i not in scenarios]
    if unknown:
        raise ValueError(f"unknown scenario ids: {unknown}")
    rows: list[dict[str, Any]] = []
    for scenario_id in ids:
        scenario = scenarios[scenario_id]
        run_dir = new_run_dir(runs_dir)
        result = investigate(
            scenario.question, make_client(), workspace, run_dir, guard=guard, reasoning=reasoning
        )
        report = write_report(run_dir, data_dir)
        rows.append(
            {
                "id": scenario_id,
                "title": scenario.title,
                "status": result.status.value,
                "model": result.model,
                "seconds": round(result.seconds, 1),
                "run_dir": str(run_dir),
                "report": str(report),
                "replay_ok": replay_run(run_dir, workspace).ok,
            }
        )
    summary = {"scenario_file": str(SCENARIO_FILE), "rows": rows}
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "demo_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return rows
