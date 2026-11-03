"""Run the adversarial scientific QA suite and write its JSON record and Markdown report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from earthlab.evals.adversarial import load_suite, render, run_case, summary

OUT = Path("docs/evidence/adversarial-qa-v1.json")
REPORT = Path("docs/adversarial-qa-v1.md")


def main() -> int:
    suite = load_suite()
    results = [run_case(case) for case in suite.cases]
    record = {"suite_version": suite.version, "summary": summary(results),
              "results": [r.model_dump() for r in results]}  # fmt: skip
    OUT.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    REPORT.write_text(render(suite, results), encoding="utf-8")
    print(json.dumps(record["summary"]))
    return 0 if all(r.correct for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
