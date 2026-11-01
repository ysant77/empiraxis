"""The typed entry point for experiment E1. There is no free-text path to this code."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from earthlab.forecast.experiment import run_experiment
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


def add_forecast_parsers(sub: Any) -> None:
    run = sub.add_parser("e1", help="experimental: historical PM2.5 evaluation, research only")
    run.add_argument(
        "--arm", choices=["deterministic", "single_agent", "multi_agent"], required=True
    )
    run.add_argument("--provider", default="local-glimmer")
    run.add_argument("--providers", type=Path, default=Path("config/providers.yaml"))
    run.add_argument("--runs-dir", type=Path, default=Path("runs"))
    run.set_defaults(func=cmd_e1)
