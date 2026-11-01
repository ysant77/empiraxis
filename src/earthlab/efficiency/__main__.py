"""Command line for the offline efficiency tools: `python -m earthlab.efficiency ...`.

Every command reads files and prints. None calls a model, reads `.env` or writes a file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from earthlab.efficiency.load import load_runs
from earthlab.efficiency.paired import load_plan, order_for
from earthlab.efficiency.prompt_review import default_specs, review_prompts
from earthlab.efficiency.report import render_markdown, summarize
from earthlab.efficiency.router import Budget, Policy, complexity_of, route
from earthlab.implement.bindings import load_bindings
from earthlab.llm.providers import load_providers


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m earthlab.efficiency")
    sub = p.add_subparsers(dest="command", required=True)
    prof = sub.add_parser("profile", help="profile recorded runs")
    prof.add_argument("--runs", type=Path, required=True, help="folder with manifest.jsonl")
    prof.add_argument("--json", action="store_true")
    rev = sub.add_parser("review", help="review the production prompts")
    rev.add_argument("--json", action="store_true")
    rt = sub.add_parser("route", help="show the routing decision for each policy")
    rt.add_argument("question")
    rt.add_argument("--case-id", default=None)
    rt.add_argument("--case-ids", nargs="*", default=["kalimantan-2015-burned-area"])
    rt.add_argument("--max-model-calls", type=int, default=40)
    rt.add_argument("--max-seconds", type=float, default=3600.0)
    rt.add_argument("--max-usd", type=float, default=1.0)
    sub.add_parser("plan", help="print the paired-task plan with policy orders")
    return p


def _profile(args: argparse.Namespace) -> str:
    profiles, anomalies = load_runs(args.runs)
    summary = summarize(profiles, anomalies)
    return json.dumps(summary, indent=1, default=str) if args.json else render_markdown(summary)


def _review(args: argparse.Namespace) -> str:
    review = review_prompts(default_specs())
    if args.json:
        return review.model_dump_json(indent=1)
    lines = [f"{f.severity:5} {f.rule} {f.prompt_id}: {f.message}" for f in review.findings]
    lines.append("Candidate changes need approval. No prompt was changed.")
    return "\n".join(lines)


def _route(args: argparse.Namespace) -> str:
    bindings = load_bindings(Path("config/roles/bindings.yaml"))
    providers = load_providers(Path("config/providers.yaml"))
    budget = Budget(
        max_model_calls=args.max_model_calls, max_seconds=args.max_seconds, max_usd=args.max_usd
    )
    cx = complexity_of(args.question, tuple(args.case_ids), args.case_id)
    policies: tuple[Policy, ...] = ("A", "B", "C")
    out = {p: route(p, cx, bindings, providers, budget).model_dump() for p in policies}
    return json.dumps(
        {"complexity": cx.model_dump() | {"level": cx.level}, "decisions": out}, indent=1
    )


def _plan() -> str:
    plan = load_plan(Path("config/efficiency/paired_tasks.yaml"))
    orders = [list(order_for(i)) for i in range(plan.design.pairs_per_task)]
    return json.dumps({"tasks": [t.model_dump() for t in plan.tasks], "orders": orders}, indent=1)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handlers = {"profile": _profile, "review": _review, "route": _route}
    text = _plan() if args.command == "plan" else handlers[args.command](args)
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
