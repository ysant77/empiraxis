"""Command line: data QA, single-claim checks, live investigations and offline replay."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from earthlab.agent.budget import Budget
from earthlab.audit import RunTrace
from earthlab.contracts import TimeWindow
from earthlab.data.quality import coverage_report
from earthlab.evals.runner import ARMS, run_suite
from earthlab.evals.tasks import load_tasks
from earthlab.llm.client import build_client
from earthlab.llm.providers import load_providers
from earthlab.metrics import EarthlabMetrics
from earthlab.report.chart import hourly_chart
from earthlab.report.markdown import render_report
from earthlab.runtime import investigate, new_run_dir, open_workspace
from earthlab.verify.claims import Claim

DEFAULT_WINDOW = TimeWindow(start=datetime(2015, 9, 1), end=datetime(2015, 11, 1))


def _print_event(record: dict[str, Any]) -> None:
    data = record["data"]
    event = record["event"]
    if event == "model_turn":
        calls = ", ".join(c["name"] for c in data["tool_calls"]) or "text answer"
        print(f"[turn {data['turn']}] model -> {calls} ({data['wall_seconds']:.1f} s)")
    elif event == "tool_result":
        line = f"    {data['name']}: {data['outcome']}"
        if data["name"] == "submit_findings" and data.get("data"):
            verdicts = [
                f"{v['kind']}/{v['region']}={v['verdict']}" for v in data["data"]["verdicts"]
            ]
            line += " | " + "; ".join(verdicts)
        elif data.get("error"):
            line += f" | {data['error'][:120]}"
        print(line)
    elif event == "finish":
        print(f"[finish] status={data['status']} ({data['reason']})")
    sys.stdout.flush()


def cmd_qa(args: argparse.Namespace) -> int:
    workspace = open_workspace(args.data_dir)
    window = TimeWindow(start=args.start, end=args.end)
    report = coverage_report(workspace.dataset, window)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    workspace = open_workspace(args.data_dir)
    claim = Claim.model_validate_json(args.claim)
    result = workspace.verifier.verify(claim)
    print(result.model_dump_json(indent=2))
    return 0 if result.verdict.value == "supported" else 1


def write_report(run_dir: Path, workspace_dir: Path) -> Path:
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    workspace = open_workspace(workspace_dir)
    hourly_chart(workspace.dataset, DEFAULT_WINDOW, run_dir / "pm25_hourly.png")
    path = run_dir / "report.md"
    path.write_text(render_report(result, "pm25_hourly.png"), encoding="utf-8")
    return path


def cmd_investigate(args: argparse.Namespace) -> int:
    config = load_providers(args.providers)[args.provider]
    client = build_client(config)
    workspace = open_workspace(args.data_dir)
    run_dir = new_run_dir(args.runs_dir)
    metrics = EarthlabMetrics()
    if args.metrics_port:
        metrics.serve(args.metrics_port)
        print(f"metrics: http://127.0.0.1:{args.metrics_port}/metrics")
    print(f"run: {run_dir}\nprovider: {config.name} ({config.model}, {config.logical_model})")
    budget = Budget(max_turns=args.max_turns, max_seconds=args.max_seconds)
    result = investigate(
        args.question,
        client,
        workspace,
        run_dir,
        metrics=metrics,
        budget=budget,
        reasoning=args.reasoning,
        listener=_print_event,
    )
    report = write_report(run_dir, args.data_dir)
    print(f"\n{result.answer}\n\nreport: {report}")
    return 0 if result.status.value in ("verified", "partial") else 2


def cmd_replay(args: argparse.Namespace) -> int:
    """Re-check a saved run without any model: trace chain plus every verdict."""
    records = RunTrace(args.run_dir / "trace.jsonl").verify()
    result = json.loads((args.run_dir / "result.json").read_text(encoding="utf-8"))
    workspace = open_workspace(args.data_dir)
    total = same = 0
    for rnd in result["rounds"]:
        for saved in rnd:
            fresh = workspace.verifier.verify(Claim.model_validate(saved["claim"]))
            total += 1
            same += fresh.verdict.value == saved["verdict"]
    print(f"trace: {records} records, hash chain intact")
    print(f"verdicts reproduced: {same}/{total}")
    print(f"status: {result['status']}; provider: {result['provider']} ({result['model']})")
    return 0 if same == total else 1


def cmd_eval(args: argparse.Namespace) -> int:
    arms = args.arms.split(",")
    unknown = set(arms) - set(ARMS)
    if unknown:
        raise SystemExit(f"unknown arms: {sorted(unknown)}")
    needs_model = any(arm != "scripted" for arm in arms)
    client = build_client(load_providers(args.providers)[args.provider]) if needs_model else None
    tasks = load_tasks(args.tasks)
    if args.only:
        tasks = [t for t in tasks if t.id in args.only.split(",")]
    out_dir = new_run_dir(args.runs_dir / "evals")
    summary = run_suite(
        tasks,
        arms,
        open_workspace(args.data_dir),
        out_dir,
        client,
        budget=Budget(max_turns=args.max_turns),
        on_score=lambda s: print(
            f"{s.task_id} [{s.arm}] met {s.met}/{s.required} success={s.verified_success}",
            flush=True,
        ),
    )
    print(json.dumps(summary, indent=2))
    print(f"results: {out_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="earthlab", description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/nea"))
    sub = parser.add_subparsers(dest="command", required=True)

    qa = sub.add_parser("qa", help="coverage and data-quality report for a window")
    qa.add_argument("--start", type=datetime.fromisoformat, default=DEFAULT_WINDOW.start)
    qa.add_argument("--end", type=datetime.fromisoformat, default=DEFAULT_WINDOW.end)
    qa.set_defaults(func=cmd_qa)

    verify = sub.add_parser("verify", help="check one claim (JSON) against the source")
    verify.add_argument("claim")
    verify.set_defaults(func=cmd_verify)

    inv = sub.add_parser("investigate", help="run a live investigation with a Meta model")
    inv.add_argument("question")
    inv.add_argument("--provider", default="local-glimmer")
    inv.add_argument("--providers", type=Path, default=Path("config/providers.yaml"))
    inv.add_argument("--runs-dir", type=Path, default=Path("runs"))
    inv.add_argument("--reasoning", choices=["low", "medium", "high"], default="low")
    inv.add_argument("--max-turns", type=int, default=12)
    inv.add_argument("--max-seconds", type=float, default=3600.0)
    inv.add_argument("--metrics-port", type=int, default=0)
    inv.set_defaults(func=cmd_investigate)

    ev = sub.add_parser("eval", help="score agent, no-tool and scripted arms on fixed tasks")
    ev.add_argument("--tasks", type=Path, default=Path("evals/tasks.yaml"))
    ev.add_argument("--arms", default="scripted")
    ev.add_argument("--only", default="")
    ev.add_argument("--provider", default="local-glimmer")
    ev.add_argument("--providers", type=Path, default=Path("config/providers.yaml"))
    ev.add_argument("--runs-dir", type=Path, default=Path("runs"))
    ev.add_argument("--max-turns", type=int, default=10)
    ev.set_defaults(func=cmd_eval)

    replay = sub.add_parser("replay", help="re-verify a saved run offline, no model needed")
    replay.add_argument("run_dir", type=Path)
    replay.set_defaults(func=cmd_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
