"""The typed entry point for experiment E1. There is no free-text path to this code."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from earthlab.forecast.experiment import run_experiment
from earthlab.forecast.tiers import run_tiers
from earthlab.harness.scenarios import SCENARIOS, SUMMARY, run_scenario
from earthlab.llm.client import build_client
from earthlab.llm.providers import load_providers
from earthlab.runtime import new_run_dir


def cmd_e1(args: argparse.Namespace) -> int:
    client = None
    if args.arm != "deterministic":
        client = build_client(load_providers(args.providers)[args.provider])
    run_dir = new_run_dir(args.runs_dir)
    done = run_experiment(args.arm, run_dir, client)
    print(f"run: {run_dir}\nstatus: {done['status']}\nreason: {done['reason']}")
    print(json.dumps(done["usage"], indent=2))
    return 0 if done["status"] == "awaiting_human" else 2


def cmd_tiers(args: argparse.Namespace) -> int:
    client = None
    if not args.no_model:
        client = build_client(load_providers(args.providers)[args.provider])
    run_dir = new_run_dir(args.runs_dir)
    done = run_tiers(run_dir, client)
    print(f"run: {run_dir}\nstatus: {done['status']}\nreason: {done['reason']}")
    print(json.dumps({k: done.get(k) for k in ("tiers", "distillation")}, indent=2))
    return 0 if done["status"] == "awaiting_human" else 2


def cmd_harness(args: argparse.Namespace) -> int:
    client = None
    if args.arm != "fixed":
        client = build_client(load_providers(args.providers)[args.provider])
    run_dir = new_run_dir(args.runs_dir)
    done = run_scenario(args.scenario, args.arm, run_dir, client)
    print(f"run: {run_dir}\nstatus: {done['status']}\nreason: {done['reason']}")
    print(json.dumps({k: done.get(k) for k in SUMMARY}, indent=2, default=str))
    return 0 if done["status"] in ("awaiting_human", "refused") else 2


def add_forecast_parsers(sub: Any) -> None:
    run = sub.add_parser("harness", help="experimental: one problem through the shared lifecycle")
    run.add_argument("scenario", choices=sorted(SCENARIOS))
    run.add_argument("--arm", choices=["fixed", "single", "team"], default="fixed")
    run.add_argument("--provider", default="local-glimmer")
    run.add_argument("--providers", type=Path, default=Path("config/providers.yaml"))
    run.add_argument("--runs-dir", type=Path, default=Path("runs"))
    run.set_defaults(func=cmd_harness)
    tiers = sub.add_parser("e1-tiers", help="experimental: teacher and student rehearsal")
    tiers.add_argument("--no-model", action="store_true")
    tiers.add_argument("--provider", default="local-glimmer")
    tiers.add_argument("--providers", type=Path, default=Path("config/providers.yaml"))
    tiers.add_argument("--runs-dir", type=Path, default=Path("runs"))
    tiers.set_defaults(func=cmd_tiers)
    run = sub.add_parser("e1", help="experimental: historical PM2.5 evaluation, research only")
    run.add_argument(
        "--arm", choices=["deterministic", "single_agent", "multi_agent"], required=True
    )
    run.add_argument("--provider", default="local-glimmer")
    run.add_argument("--providers", type=Path, default=Path("config/providers.yaml"))
    run.add_argument("--runs-dir", type=Path, default=Path("runs"))
    run.set_defaults(func=cmd_e1)
