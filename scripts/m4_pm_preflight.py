"""Check one running model server in the product-manager seat. It starts no server."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from earthlab.harness import pm_check
from earthlab.llm.client import build_client
from earthlab.llm.providers import load_providers

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "examples" / "replay" / "scenario-muse-method-comparison" / "evaluation-plan-1.json"


def main() -> int:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("--provider", required=True)
    top.add_argument("--out", type=Path, required=True)
    args = top.parse_args()
    cfg = load_providers(ROOT / "config" / "providers.yaml")[args.provider]
    rows = pm_check.run(build_client(cfg), REPORT, args.out / f"pm-{args.provider}")
    result = {"provider": args.provider, "passed": pm_check.passed(rows), "cases": rows}
    (args.out / f"pm-{args.provider}.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
