"""Run review-gate validation v1. It starts no model server and needs Muse on port 8080.

cases:   the seeded cases. A case without a critic runs once and needs no model.
matched: the matched live runs, gate and plain, in the frozen order.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from earthlab.harness.matrix_run import git_state, pin_problems
from earthlab.harness.review_validation import facts_for, load_cases, needs_model, run_case
from earthlab.harness.scenarios import run_scenario
from earthlab.llm.client import ChatClient, build_client
from earthlab.llm.providers import load_providers
from earthlab.runtime import new_run_dir

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
EVIDENCE_ROOT = ROOT.parent


def row_out(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str) + "\n")
    name, state = row.get("case") or row.get("scenario"), row.get("verdict") or row.get("status")
    print(name, row.get("gate", ""), state, row.get("wall_seconds", ""), flush=True)


def cases(args: argparse.Namespace, client: ChatClient) -> None:
    plan = load_cases(CONFIG / "benchmark" / "review_validation.yaml")
    for case in plan.cases:
        if args.only and case.id not in args.only:
            continue
        probe, _ = facts_for(case, new_run_dir(args.out / "cases"))
        repeats = plan.critic_repeats if needs_model(case, probe) else 1
        for repeat in range(1, repeats + 1):
            try:
                row = run_case(case, new_run_dir(args.out / "cases"), EVIDENCE_ROOT, client)
            except Exception as exc:  # a crash is a result, so the next case still runs
                row = {"case": case.id, "verdict": "crashed", "err": str(exc)[:300]}
            row_out(args.out / "cases.jsonl", row | {"repeat": repeat})


def matched(args: argparse.Namespace, client: ChatClient) -> None:
    plan = load_cases(CONFIG / "benchmark" / "review_validation.yaml")
    for pair in plan.matched.pairs:
        for side in pair.order:
            run_dir, began = new_run_dir(args.out / "matched"), time.perf_counter()
            row: dict[str, Any] = {"scenario": pair.scenario, "gate": side, "run": str(run_dir)}
            try:
                done = run_scenario(
                    pair.scenario, plan.matched.arm, run_dir, client, method_review=side == "gate"
                )
                row |= {k: done.get(k) for k in (
                    "status", "reason", "recommendation", "code_outcome", "acceptance", "usage",
                    "method_review", "claims", "refusal_codes",
                )}  # fmt: skip
            except Exception as exc:  # a crash is a result, so the pair still completes
                row |= {"status": "crashed", "err": str(exc)[:300]}
            row["wall_seconds"] = round(time.perf_counter() - began, 1)
            row_out(args.out / "matched.jsonl", row)


def main() -> int:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("step", choices=["cases", "matched"])
    top.add_argument("--commit", required=True)
    top.add_argument("--out", type=Path, required=True)
    top.add_argument("--only", nargs="*", help="case IDs, for a later experiment ID")
    args = top.parse_args()
    head, dirty = git_state(ROOT)
    wrong = pin_problems(args.commit, head, dirty)
    if wrong:
        print("; ".join(wrong), file=sys.stderr)
        return 3
    args.out.mkdir(parents=True, exist_ok=True)
    plan = load_cases(CONFIG / "benchmark" / "review_validation.yaml")
    client = build_client(load_providers(CONFIG / "providers.yaml")[plan.matched.provider])
    {"cases": cases, "matched": matched}[args.step](args, client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
