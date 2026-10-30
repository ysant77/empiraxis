"""Command line: data QA, single-claim checks, live investigations and offline replay."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from earthlab.acquire.gate import load_approvals
from earthlab.acquire.run import acquire_era5, acquire_firms, acquire_mcd64a1, write_manifest
from earthlab.agent.budget import Budget
from earthlab.bench.heldout import HeldoutError, load_lock, scenario_file_record
from earthlab.bench.official import OfficialSetup, check_only, run_official
from earthlab.bench.protocol import load_protocol
from earthlab.bench.runner import ARMS as BENCH_ARMS
from earthlab.bench.runner import run_bench
from earthlab.bench.scenarios import ScenarioScore, load_scenarios
from earthlab.cases.loader import load_case
from earthlab.contracts import TimeWindow
from earthlab.data.quality import coverage_report
from earthlab.demo import DEMO_IDS, run_demo
from earthlab.evals.runner import ARMS, run_suite
from earthlab.evals.safety import load_cases, run_case, summarize
from earthlab.evals.tasks import load_tasks
from earthlab.haze.cli import add_haze_parsers
from earthlab.llm.client import build_client
from earthlab.llm.providers import load_providers
from earthlab.llm.raw import RawCompletionClient
from earthlab.llm.retry import RetryPolicy
from earthlab.metrics import EarthlabMetrics
from earthlab.report.write import DEFAULT_WINDOW, write_report
from earthlab.runtime import RunOptions, investigate, new_run_dir, open_workspace
from earthlab.safety.llama_guard import LlamaGuard
from earthlab.tools.burned_area_tools import case_report
from earthlab.verify.claims import Claim
from earthlab.verify.replay import replay_run
from earthlab.workflow.run import run_workflow


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
    elif event == "safety_check":
        verdict = "allowed" if data["allowed"] else f"BLOCKED by {data['blocked_by']}"
        print(f"[safety {data['stage']}] {verdict} | {data.get('guard') or 'rules only'}")
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


def cmd_report(args: argparse.Namespace) -> int:
    print(f"report: {write_report(args.run_dir, args.data_dir)}")
    return 0


def build_guard(providers: Path, name: str) -> LlamaGuard | None:
    """The safety model, or None when explicitly disabled with --guard none."""
    if name == "none":
        return None
    config = load_providers(providers)[name]
    return LlamaGuard(RawCompletionClient(config), config.logical_model)


def exit_code(status: str) -> int:
    """0 only for a verified run (claims and text); 2 for every other outcome, even partial."""
    return 0 if status == "verified" else 2


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
        guard=build_guard(args.providers, args.guard),
        options=_run_options(args),
    )
    report = write_report(run_dir, args.data_dir)
    for finding_id, r in result.ledger.latest_by_id().items():
        c = r.claim
        fact = f"{c.kind.value} {c.region.value} = {r.observed} {c.unit}"
        print(f"{finding_id} {r.verdict.value}: {fact}")
    print(f"\n{result.answer}\n\nreport: {report}")
    for issue in result.answer_issues:
        print(f"answer not verified: {issue}")
    return exit_code(result.status.value)


def cmd_workflow(args: argparse.Namespace) -> int:
    """Product manager -> Geospatial Engineer hand-off; one provider serves both roles."""
    config = load_providers(args.providers)[args.provider]
    client = build_client(config)
    run_dir = new_run_dir(args.runs_dir)
    print(f"run: {run_dir}\nprovider: {config.name} ({config.model}) for PM and engineer")
    run = run_workflow(
        args.question,
        client,
        open_workspace(args.data_dir),
        run_dir,
        budget=Budget(max_turns=args.max_turns, max_seconds=args.max_seconds),
        reasoning=args.reasoning,
        listener=_print_event,
        guard=build_guard(args.providers, args.guard),
        options=_run_options(args),
    )
    if run.brief is not None:
        print(f"brief: route {run.brief.brief.route}, case {run.brief.brief.case_id}")
    for question in run.manager.followup_questions:
        print(f"needs input: {question}")
    if run.engineer is not None:
        print(f"report: {write_report(run_dir, args.data_dir)}")
    print(f"\n{run.manager.report_text}\n\nstatus: {run.status} ({run.manager.report_source})")
    return exit_code(run.status)


def cmd_replay(args: argparse.Namespace) -> int:
    """Re-check a saved run without any model: trace chain, verdicts and input hashes."""
    out = replay_run(args.run_dir, open_workspace(args.data_dir))
    print(f"trace: {out.trace_records} records, hash chain intact")
    print(f"verdicts reproduced: {out.pm25[0]}/{out.pm25[1]}")
    print(f"area verdicts reproduced: {out.area[0]}/{out.area[1]}")
    print(f"month checks reproduced: {out.months[0]}/{out.months[1]}")
    if not out.files_checked:
        print("input hashes: none recorded")
    elif not out.changed_files:
        print(f"input hashes: all match ({out.files_checked} files)")
    else:
        print(f"input hashes: {len(out.changed_files)} of {out.files_checked} files CHANGED")
    for rel in out.changed_files:
        print(f"changed: {rel}")
    for problem in out.problems:
        print(f"problem: {problem}")
    return 0 if out.ok else 1


def cmd_demo(args: argparse.Namespace) -> int:
    """The wildfire demo with the Meta agent: one run, report and replay per question."""
    config = load_providers(args.providers)[args.provider]
    ids = args.only.split(",") if args.only else list(DEMO_IDS)
    rows = run_demo(
        ids,
        lambda: build_client(config),
        open_workspace(args.data_dir),
        new_run_dir(args.runs_dir / "demo"),
        args.data_dir,
        guard=build_guard(args.providers, args.guard),
        reasoning=args.reasoning,
    )
    for r in rows:
        replay = "replay ok" if r["replay_ok"] else "REPLAY FAILED"
        print(f"{r['id']:7} {r['status']:18} {r['seconds']:7.1f} s  {replay}  {r['report']}")
    return 0 if all(r["replay_ok"] for r in rows) else 1


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


def cmd_acquire(args: argparse.Namespace) -> int:
    """Download one case asset after its recorded approvals are checked; write a manifest."""
    case_file = load_case(args.case, Path.cwd())
    approvals = load_approvals(args.approvals)
    product = case_file.assets[args.asset].product
    if product.startswith("MODIS/061/MCD64A1"):
        import os

        import ee  # optional extra: uv sync --extra acquire

        ee.Initialize(project=os.environ["EE_PROJECT"])
        manifest = acquire_mcd64a1(case_file, args.asset, approvals, args.out, ee)
    elif product.startswith("FIRMS/"):
        manifest = acquire_firms(case_file, args.asset, approvals, args.out)
    elif product.startswith("ERA5/"):
        manifest = acquire_era5(case_file, args.asset, approvals, args.out)
    else:
        raise SystemExit(f"no acquisition route for {product}")
    path = write_manifest(manifest, args.out)
    print(json.dumps({"manifest": str(path), "files": manifest["files"]}, indent=2, default=str))
    return 0


def cmd_burned_area(args: argparse.Namespace) -> int:
    """MCD64A1 burned area for every pinned month of a case, with the verifier's checks."""
    reports = case_report(load_case(args.case, Path.cwd()), Path.cwd())
    for r in reports:
        s, c = r["summary"], r["check"]
        verdict = "PASS" if c["passed"] else "FAIL"
        gate = "reportable" if s["gate_passed"] else "insufficient_data"
        print(
            f"{r['month']}: {s['primary_area_ha']:.1f} ha mapped burned ({s['burned_pixels']} px), "
            f"valid {s['valid_fraction']:.3f} -> {gate}; checks {verdict} "
            f"(EE {c['ee_burned_pixels']} px, allowed diff {c['allowed_count_difference']})"
        )
    if args.output:
        args.output.write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    return 0 if all(r["check"]["passed"] for r in reports) else 1


def _add_acquire_parser(sub: Any) -> None:
    area = sub.add_parser("burned-area", help="MCD64A1 burned area for a pinned case, verified")
    area.add_argument("--case", type=Path, required=True)
    area.add_argument("--output", type=Path, default=None)
    area.set_defaults(func=cmd_burned_area)

    acq = sub.add_parser("acquire", help="download one approved case asset (needs approvals)")
    acq.add_argument("--case", type=Path, required=True)
    acq.add_argument("--asset", required=True)
    acq.add_argument("--approvals", type=Path, default=Path("config/approvals"))
    acq.add_argument("--out", type=Path, required=True)
    acq.set_defaults(func=cmd_acquire)


def cmd_bench(args: argparse.Namespace) -> int:
    """ScienceBench: arm A (rule dispatcher) and arm B (Meta agent) on ready scenarios."""
    arms = args.arms.split(",")
    if set(arms) - set(BENCH_ARMS):
        raise SystemExit(f"unknown arms: {sorted(set(arms) - set(BENCH_ARMS))}")
    client = build_client(load_providers(args.providers)[args.provider]) if "B" in arms else None
    scenarios = load_scenarios(args.scenarios)
    lock = load_lock(args.heldout_lock) if args.heldout_lock else None
    if lock is not None and args.only:
        raise HeldoutError("--only is not allowed with --heldout-lock: run the whole set")
    scenario_file = scenario_file_record(args.scenarios, scenarios, lock)
    if args.only:
        scenarios = [s for s in scenarios if s.id in args.only.split(",")]
    out_dir = new_run_dir(args.runs_dir / "bench")
    summary = run_bench(
        scenarios,
        arms,
        open_workspace(args.data_dir),
        out_dir,
        repo=Path.cwd(),
        client=client,
        guard=build_guard(args.providers, args.guard) if client else None,
        budget=Budget(max_turns=args.max_turns),
        repeats=args.repeats,
        scenario_file=scenario_file,
        reasoning=args.reasoning,
        on_score=_print_score,
        options=RunOptions() if lock else _run_options(args),
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "meta"}, indent=2))
    print(f"results: {out_dir}")
    return 0


def _print_score(s: ScenarioScore) -> None:
    print(
        f"{s.scenario_id} [{s.arm}] r{s.repeat} passed={s.passed} {'; '.join(s.reasons)}",
        flush=True,
    )


PROVIDERS = Path("config/providers.yaml")  # pinned by hash in the protocol


def cmd_bench_official(args: argparse.Namespace) -> int:
    """The one official held-out run. It takes no tuning flags: the protocol fixes them."""
    protocol = load_protocol(args.protocol)
    providers = load_providers(PROVIDERS)
    client = build_client(providers[protocol.provider]) if "B" in protocol.arms else None
    guard = build_guard(PROVIDERS, protocol.guard) if client else None
    setup = OfficialSetup(
        Path.cwd(), protocol, args.scenarios, open_workspace(args.data_dir), client, guard
    )
    if args.check_only:
        meta = check_only(setup)
        print(f"protocol check passed at {meta['code_revision']}; no question was run")
        return 0
    out_dir, summary = run_official(setup, args.rerun_reason, _print_score)
    print(json.dumps({k: v for k, v in summary.items() if k != "meta"}, indent=2))
    print(f"official results: {out_dir}")
    return 0


def cmd_safety_eval(args: argparse.Namespace) -> int:
    guard = build_guard(args.providers, args.guard)
    results = [run_case(case, guard) for case in load_cases(args.cases)]
    for r in results:
        print(
            f"{r.case.id:24} expected={'allow' if r.case.allowed else 'block':5} "
            f"guard={r.guard_allows} rules={r.rules_allow} gate={r.gate_allows}",
            flush=True,
        )
    print(json.dumps(summarize(results), indent=2))
    return 0


def _add_eval_parser(sub: Any) -> None:
    ev = sub.add_parser(
        "eval", help="older smoke eval; its scripted arm is an oracle that reads requirements"
    )
    ev.add_argument("--tasks", type=Path, default=Path("evals/tasks.yaml"))
    ev.add_argument("--arms", default="scripted")
    ev.add_argument("--only", default="")
    ev.add_argument("--provider", default="local-glimmer")
    ev.add_argument("--providers", type=Path, default=Path("config/providers.yaml"))
    ev.add_argument("--runs-dir", type=Path, default=Path("runs"))
    ev.add_argument("--max-turns", type=int, default=10)
    ev.set_defaults(func=cmd_eval)


def _run_options(args: argparse.Namespace) -> RunOptions:
    retry = RetryPolicy() if args.provider_retry else None
    return RunOptions(args.plan_review, args.render_fallback, retry)


def _add_plan_flag(parser: Any) -> None:
    parser.add_argument(
        "--no-plan-review",
        dest="plan_review",
        action="store_false",
        help="skip the typed plan and critic step (the agent arm before plan review)",
    )
    parser.add_argument(
        "--no-rendered-fallback",
        dest="render_fallback",
        action="store_false",
        help="keep a final text that fails the answer audit as answer_unverified",
    )
    parser.add_argument(
        "--provider-retry",
        action="store_true",
        help="retry a model call once after a transient provider failure (off in v1 protocol)",
    )


def _add_bench_parser(sub: Any) -> None:
    bench = sub.add_parser("bench", help="ScienceBench: rule dispatcher vs Meta agent")
    bench.add_argument("--scenarios", type=Path, default=Path("evals/sciencebench_dev_v1.yaml"))
    bench.add_argument("--heldout-lock", type=Path, help="lock file of a sealed held-out set")
    bench.add_argument("--arms", default="A")
    bench.add_argument("--only", default="")
    bench.add_argument("--repeats", type=int, default=1)
    bench.add_argument("--provider", default="local-glimmer")
    bench.add_argument("--providers", type=Path, default=Path("config/providers.yaml"))
    bench.add_argument("--guard", default="local-llama-guard")
    bench.add_argument("--runs-dir", type=Path, default=Path("runs"))
    bench.add_argument("--max-turns", type=int, default=12)
    bench.add_argument("--reasoning", default="low", choices=["low", "medium", "high"])
    _add_plan_flag(bench)
    bench.set_defaults(func=cmd_bench)


def _add_official_parser(sub: Any) -> None:
    official = sub.add_parser("bench-official", help="the one official held-out run")
    official.add_argument("--protocol", type=Path, required=True)
    official.add_argument("--scenarios", type=Path, required=True, help="sealed question file")
    official.add_argument("--rerun-reason", help="required for a second official run")
    official.add_argument("--check-only", action="store_true", help="check; run no question")
    official.set_defaults(func=cmd_bench_official)


def _add_demo_parser(sub: Any) -> None:
    demo = sub.add_parser("demo", help="wildfire demo: Meta agent run, report, replay")
    demo.add_argument("--only", help="comma-separated scenario ids (default: the demo set)")
    demo.add_argument("--provider", default="local-glimmer")
    demo.add_argument("--providers", type=Path, default=Path("config/providers.yaml"))
    demo.add_argument("--runs-dir", type=Path, default=Path("runs"))
    demo.add_argument("--reasoning", choices=["low", "medium", "high"], default="low")
    demo.add_argument("--guard", default="local-llama-guard", help="safety provider, or 'none'")
    demo.set_defaults(func=cmd_demo)


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
    inv.add_argument(
        "--guard", default="local-llama-guard", help="safety model provider, or 'none'"
    )
    _add_plan_flag(inv)
    inv.set_defaults(func=cmd_investigate)

    flow = sub.add_parser(
        "workflow", help="experimental: product manager -> geospatial engineer hand-off"
    )
    flow.add_argument("question")
    flow.add_argument("--provider", default="local-glimmer")
    flow.add_argument("--providers", type=Path, default=Path("config/providers.yaml"))
    flow.add_argument("--runs-dir", type=Path, default=Path("runs"))
    flow.add_argument("--reasoning", choices=["low", "medium", "high"], default="low")
    flow.add_argument("--max-turns", type=int, default=12)
    flow.add_argument("--max-seconds", type=float, default=3600.0)
    flow.add_argument(
        "--guard", default="local-llama-guard", help="safety model provider, or 'none'"
    )
    _add_plan_flag(flow)
    flow.set_defaults(func=cmd_workflow)

    _add_eval_parser(sub)
    _add_bench_parser(sub)
    _add_official_parser(sub)

    _add_acquire_parser(sub)
    add_haze_parsers(sub)

    safety = sub.add_parser("safety-eval", help="score Llama Guard and scope rules on labels")
    safety.add_argument("--cases", type=Path, default=Path("evals/safety_cases.yaml"))
    safety.add_argument("--providers", type=Path, default=Path("config/providers.yaml"))
    safety.add_argument("--guard", default="local-llama-guard")
    safety.set_defaults(func=cmd_safety_eval)

    _add_demo_parser(sub)
    replay = sub.add_parser("replay", help="re-verify a saved run offline, no model needed")
    replay.add_argument("run_dir", type=Path)
    replay.set_defaults(func=cmd_replay)
    report = sub.add_parser("report", help="render report.md for a saved run, no model needed")
    report.add_argument("run_dir", type=Path)
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
