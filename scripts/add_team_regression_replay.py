"""Add the recorded Muse team regression run (M2) to the replay folder.

Only the new folder and its manifest entry are written. S1 to S4 and M1 are not touched.
Model text and reasoning are removed; typed choices and code's checks stay.

Run with:  uv run python scripts/add_team_regression_replay.py <run folder>
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
RUN = "scenario-muse-team-regression"


def main() -> int:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("source", type=Path)
    source = top.parse_args().source.resolve()
    kept = [r for r in listed_runs(OUT) if r["run"] != RUN]
    run_dir = OUT / RUN
    if run_dir.exists():
        shutil.rmtree(run_dir)
    removed = copy_redacted_harness(source, run_dir)
    for evaluation in sorted((source / "artifacts").glob("evaluation-*.json")):
        shutil.copyfile(evaluation, run_dir / evaluation.name)
    entry = {
        "run": RUN, "scenario_id": "M2", "removed_fields": sorted(removed),
        "label": "real Muse Glimmer team run; redacted copy",
        "source_trace_sha256": file_digest(source / "trace.jsonl"),
        "evidence_mode": "Real Muse Glimmer team run, recorded replay, redacted copy.",
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
