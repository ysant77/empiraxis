"""Build the integrated comparative report from saved records. No model runs.

Run with:  uv run python scripts/build_comparative_report.py <folder that holds the run folders>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from earthlab.harness.compare import NOT_MEASURED
from earthlab.harness.comparative import by_arm, coverage, matched, scored, selection
from earthlab.harness.replay import MissingArtifact, replay_run
from earthlab.trace import TraceIntegrityError

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "evidence" / "comparative-v1.json"
MATRIX = "earthlab-matrix-runs/decisions-v1"
SOURCES = {
    "benchmark screen": f"{MATRIX}/screen-muse/manifest.jsonl",
    "benchmark confirm": f"{MATRIX}/confirm/manifest.jsonl",
    "benchmark fallback": f"{MATRIX}/fallback-single/manifest.jsonl",
    "harness-v1": "earthlab-e1-runs/harness-v1/manifest.jsonl",
}
REVIEW = "earthlab-review-validation"


def clean(run: Path) -> bool:
    try:
        return not replay_run(run)["mismatches"]
    except (MissingArtifact, TraceIntegrityError, FileNotFoundError, KeyError, ValueError):
        return False


def review_rows(root: Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((root / REVIEW).glob("*/*.jsonl")):
        rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        out[f"{path.parent.name}/{path.stem}"] = rows
    return out


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    runs = [r for s, m in SOURCES.items() for r in scored(s, root / m, clean)]
    report = {
        "version": 1, "runs": len(runs), "not_measured": NOT_MEASURED,
        "arms": by_arm(runs), "coverage": coverage(runs),
        "matched_screen": matched(runs, ("F", "S-M", "T-M-v1"), "benchmark screen"),
        "matched_confirm": matched(runs, ("T-M-base", "T-M-win"), "benchmark confirm"),
        "selection": selection(runs), "review": review_rows(root),
    }  # fmt: skip
    OUT.write_text(json.dumps(report, indent=1) + "\n", "utf-8")
    print(f"{len(runs)} runs written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
