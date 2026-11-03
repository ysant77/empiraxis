"""Add a recorded team run (M2, M3 or the M4 council run, with --key) to the replay folder.

Only the new folder and its manifest entry are written. Other runs are not touched.
Model text and reasoning are removed; typed choices and code's checks stay.

Run with:  uv run python scripts/add_team_regression_replay.py <run folder> [--key M3]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from earthlab.digest import file_digest
from earthlab.events.fixture import copy_redacted_harness
from earthlab.events.manifest import listed_runs, read_manifest, write_manifest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "replay"
RUNS = {
    "M2": "scenario-muse-team-regression",
    "M3": "scenario-muse-method-comparison",
    "M4": "scenario-m4-heterogeneous-council",
}
DEFAULT_LABEL = (
    "real Muse Glimmer team run; redacted copy",
    "Real Muse Glimmer team run, recorded replay, redacted copy.",
)
LABELS = {
    "M4": (
        "real heterogeneous council run (Muse and Llama 3.2 3B); redacted copy",
        "Real local run with different checkpoints in different seats, recorded replay, "
        "redacted copy.",
    ),
}


def main() -> int:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("source", type=Path)
    top.add_argument("--key", choices=sorted(RUNS), default="M2")
    args = top.parse_args()
    source, key = args.source.resolve(), args.key
    RUN = RUNS[key]
    kept = [r for r in listed_runs(OUT) if r["run"] != RUN]
    run_dir = OUT / RUN
    if run_dir.exists():
        shutil.rmtree(run_dir)
    removed = copy_redacted_harness(source, run_dir)
    for evaluation in sorted((source / "artifacts").glob("evaluation-*.json")):
        shutil.copyfile(evaluation, run_dir / evaluation.name)
    entry = {
        "run": RUN, "scenario_id": key, "removed_fields": sorted(removed),
        "label": LABELS.get(key, DEFAULT_LABEL)[0],
        "source_trace_sha256": file_digest(source / "trace.jsonl"),
        "evidence_mode": LABELS.get(key, DEFAULT_LABEL)[1],
        "science_label": "simulated_availability_hindcast",
        "planned": "A human decision on the outcome is still open.",
        "split": "validation only; the sealed test period was not read",
        "result_sha256": file_digest(run_dir / "result.json"),
    }  # fmt: skip
    write_manifest(OUT, [*kept, entry], note=str(read_manifest(OUT)["note"]))
    print(f"{RUN} added; {len(kept)} other runs kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
