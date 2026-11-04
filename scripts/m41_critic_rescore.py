"""Rescore recorded critic runs with the m41-v2 scoring. Calls no model.

The m41-v1 result files stay as they are. This script reads the critiques that the trace of
each run recorded and writes `critic-<tag>.m41-v2.json` beside them. A case with no recorded
critique counts as not usable, as in the original run.

Usage: python scripts/m41_critic_rescore.py --runs DIR [--out DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from earthlab.assess.contracts import CRITIC_CONTRACTS, EvidencePackageV1
from earthlab.assess.critic_bench import load_cases, load_seeded, rule_critique, run_bench
from earthlab.trace import RunTrace

PACKAGES = Path("examples/assess/packages")


def packages() -> dict[str, EvidencePackageV1]:
    found: dict[str, EvidencePackageV1] = {}
    for path in sorted(PACKAGES.glob("*.json")):
        pkg = EvidencePackageV1.model_validate_json(path.read_text())
        found.setdefault(pkg.package_id[0], pkg)  # cases use packages A to D only
    return found


def recorded(trace_path: Path, contract: str) -> dict[str, Any]:
    """Critiques by case id from a verified trace."""
    trace = RunTrace(trace_path)
    trace.verify()
    model = CRITIC_CONTRACTS[contract]
    return {
        r["data"]["case"]: model.model_validate(r["data"]["output"])
        for r in trace.records()
        if r["event"] == "role_output"
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    out_dir = a.out or a.runs
    cases = load_cases(Path("examples/assess/critic-cases.json"))
    seeded = load_seeded(Path("examples/assess/critic-case-evidence.json"))
    pkgs = packages()
    for old in sorted(a.runs.glob("critic-*.json")):
        if old.name.endswith(".m41-v2.json"):
            continue
        tag = old.stem.removeprefix("critic-")
        if tag == "rules":
            critic: Any = lambda case, pkg: rule_critique(case.plan, pkg)  # noqa: E731
        else:
            got = recorded(old.with_suffix(".trace.jsonl"), "v2" if tag.endswith("-v2") else "v1")
            critic = lambda case, pkg, got=got: got.get(case.id)  # noqa: E731
        scores, totals = run_bench(cases, pkgs, critic, seeded)
        body = {
            "critic": tag,
            "scoring": "m41-v2",
            "rescored_from": old.name,
            "summary": totals,
            "cases": [s.model_dump(mode="json") for s in scores],
        }
        (out_dir / f"critic-{tag}.m41-v2.json").write_text(json.dumps(body, indent=1) + "\n")
        print(tag, json.dumps(totals), flush=True)


if __name__ == "__main__":
    main()
