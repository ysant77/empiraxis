"""Command-line entry points for one bounded specialist delegation and its offline replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from earthlab.implement.bindings import load_bindings
from earthlab.llm.client import build_client
from earthlab.llm.providers import load_providers
from earthlab.runtime import new_run_dir, open_workspace
from earthlab.team.delegate import replay_delegation, run_delegation
from earthlab.team.request_flow import run_request
from earthlab.workflow.assign import BINDINGS_FILE


def cmd_delegate(args: argparse.Namespace) -> int:
    providers = load_providers(args.providers)
    bindings = load_bindings(BINDINGS_FILE)
    lead, worker = providers[args.provider], providers[args.specialist_provider]
    bindings.bind_runtime(
        "geospatial_engineer", args.candidate, lead, providers, allow_experimental=True
    )
    bindings.bind_runtime(
        "data_specialist", args.specialist_candidate, worker, providers, allow_experimental=True
    )
    run_dir = new_run_dir(args.runs_dir)
    done = run_delegation(
        args.parent,
        build_client(lead),
        build_client(worker),
        open_workspace(args.data_dir),
        run_dir,
    )
    print(f"run: {run_dir}\nstatus: {done.status}")
    return 0 if done.status == "verified" else 2


def cmd_replay_delegation(args: argparse.Namespace) -> int:
    report = replay_delegation(args.run, open_workspace(args.data_dir))
    print(json.dumps(report, indent=2))
    return 0 if report["acceptance_same"] and report["rows_hash_same"] else 1


MOCK_NEED: dict[str, Any] = {
    "need": "A second quality table for the month, to cross-check the reporting gate.",
    "asset": "mock quality table (local test server, not real data)",
    "max_bytes": 4096,
    "content_types": ["text/csv"],
    "license_terms": "mock terms for a local demonstration",
    "credential_name": "MOCK_API_TOKEN",
}


def cmd_resource_request(args: argparse.Namespace) -> int:
    config = load_providers(args.providers)[args.provider]
    need = {**MOCK_NEED, "url": args.url}
    view = run_request(args.runs_dir, build_client(config), need, args.request_id, args.parent_task)
    print(f"request: {args.request_id}\nstatus: {view.status}\nreviewers: {view.reviewers}")
    return 0 if view.status == "pm_endorsed" else 2


def add_team_parsers(sub: Any) -> None:
    run = sub.add_parser("delegate", help="experimental: Lead -> data specialist on a saved run")
    run.add_argument("parent", type=Path)
    run.add_argument("--provider", default="local-glimmer")
    run.add_argument("--candidate", default="muse-glimmer")
    run.add_argument("--specialist-provider", default="local-glimmer")
    run.add_argument("--specialist-candidate", default="muse-glimmer")
    run.add_argument("--providers", type=Path, default=Path("config/providers.yaml"))
    run.add_argument("--runs-dir", type=Path, default=Path("runs"))
    run.set_defaults(func=cmd_delegate)
    ask = sub.add_parser("resource-request", help="experimental: mock request, stops at a person")
    ask.add_argument("request_id")
    ask.add_argument("--url", required=True)
    ask.add_argument("--parent-task", default="demo.lead.data")
    ask.add_argument("--provider", default="local-glimmer")
    ask.add_argument("--providers", type=Path, default=Path("config/providers.yaml"))
    ask.add_argument("--runs-dir", type=Path, default=Path("runs"))
    ask.set_defaults(func=cmd_resource_request)
    replay = sub.add_parser("replay-delegation", help="recompute a delegation, no model needed")
    replay.add_argument("run", type=Path)
    replay.set_defaults(func=cmd_replay_delegation)
