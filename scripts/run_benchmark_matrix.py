"""Plan or run the benchmark matrix. It starts no model server.

plan: print the run order and the wall-time estimate of the named stages.
run:  run one block of one stage, after the commit pin and the binding gates pass.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from earthlab.harness.identity import load_registry
from earthlab.harness.matrix import estimate_hours, expand, load_plan
from earthlab.harness.matrix_run import Refused, run_stage
from earthlab.harness.variants import load_variants
from earthlab.implement.bindings import Bindings
from earthlab.llm.providers import load_providers

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def show(args: argparse.Namespace) -> int:
    plan = load_plan(CONFIG / "benchmark" / args.matrix)
    for stage in args.stage:
        for r in expand(plan, stage):
            print(f"{r.stage} r{r.repeat} #{r.order} [{r.block}] {r.scenario} {r.arm_id}")
    print(f"estimated hours: {estimate_hours(plan, args.stage)}")
    return 0


def run(args: argparse.Namespace) -> int:
    import yaml

    plan = load_plan(CONFIG / "benchmark" / args.matrix)
    registry = load_registry(CONFIG / "benchmark" / "checkpoints.yaml")
    bindings = Bindings.model_validate(
        yaml.safe_load((CONFIG / "roles" / "bindings.yaml").read_text(encoding="utf-8"))
    )
    try:
        rows = run_stage(
            plan, args.stage, args.block,
            variants=load_variants(CONFIG / "benchmark" / "prompt_variants.yaml"),
            providers=load_providers(CONFIG / "providers.yaml"), bindings=bindings,
            pin=args.commit, repo=ROOT, out_dir=args.out, winner=args.winner,
            minutes_left=args.minutes_left, registry=registry, matrix_file=args.matrix,
            only_arms=frozenset(args.arm) or None,
        )  # fmt: skip
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3
    bad = [r for r in rows if r["exit"] != 0]
    print(f"{len(rows)} runs written to {args.out / 'manifest.jsonl'}; {len(bad)} not clean")
    return 1 if bad else 0


def main() -> int:
    top = argparse.ArgumentParser(description=__doc__)
    sub = top.add_subparsers(required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--matrix", default="matrix.yaml")
    plan.add_argument("stage", nargs="+")
    plan.set_defaults(func=show)
    go = sub.add_parser("run")
    go.add_argument("--matrix", default="matrix.yaml")
    go.add_argument("stage")
    go.add_argument("--block", required=True, help="none, muse, or muse+<small provider>")
    go.add_argument("--commit", required=True, help="the pinned commit, at least 12 characters")
    go.add_argument("--out", type=Path, required=True)
    go.add_argument("--arm", action="append", default=[], help="run only this arm; repeatable")
    go.add_argument("--winner", help="the screening winner, for arms that use @winner")
    go.add_argument("--minutes-left", type=float, help="stop before a run that would overrun")
    go.set_defaults(func=run)
    args = top.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
