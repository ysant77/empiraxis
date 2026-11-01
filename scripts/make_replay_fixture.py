"""Rebuild the offline replay fixture under examples/replay/ from a development bench run.

Each run is a redacted, re-chained copy of a real Muse Glimmer arm B run that passed:
SB-05 (September, verified) and SB-05b (October, abstained on the coverage gate).
The source bench folder is read only. Held-out sources are refused.

Run with:
  uv run python scripts/make_replay_fixture.py <path to runs/bench/<bench id>>

A rebuild removes added workflow runs, so add them again after it.
Add one live workflow run to the existing fixture:
  uv run python scripts/make_replay_fixture.py --add NAME SCENARIO STATUS COMMIT <run folder>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from earthlab.events.fixture import LABEL, copy_redacted, copy_redacted_workflow
from earthlab.events.manifest import listed_runs, read_manifest, write_manifest
from earthlab.report.write import write_report

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "replay"
NEA = ROOT / "data" / "nea"
DEFAULT_BENCH = "20261029T020831Z-78451c"  # T9 development bench
# Replay folder name -> source run folder (scenario and repeat that passed on arm B).
RUNS = {"sb05-september": "SB-05-r0", "sb05b-october": "SB-05b-r2"}
NOTE = (
    f"{LABEL}. Model reasoning, raw model message text and provider request IDs are "
    "removed; the trace is re-chained with the source timestamps. The research questions "
    "are visible development questions and are kept."
)


def build(bench_dir: Path, out: Path = OUT) -> list[dict[str, Any]]:
    shutil.rmtree(out, ignore_errors=True)
    entries: list[dict[str, Any]] = []
    for name, source_run in RUNS.items():
        run_dir = out / name
        provenance = copy_redacted(bench_dir, source_run, run_dir)
        write_report(run_dir, NEA)
        entries.append({"run": name, **provenance})
    write_manifest(out, entries, note=NOTE)
    return entries


def add_workflow(
    name: str, scenario: str, status: str, commit: str, source: Path, out: Path = OUT
) -> dict[str, Any]:
    """Add or replace one redacted workflow run. The other runs stay as they are."""
    entries = [e for e in listed_runs(out) if e["run"] != name]
    note = str(read_manifest(out).get("note", ""))
    run_dir = out / name
    provenance = copy_redacted_workflow(source, run_dir, scenario, status, commit)
    for chart in source.glob("*.png"):
        shutil.copyfile(chart, run_dir / chart.name)
    write_report(run_dir, NEA)
    write_manifest(out, [*entries, {"run": name, **provenance}], note=note)
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    if sys.argv[1:2] == ["--add"]:
        name, scenario, status, commit, source = sys.argv[2:7]
        print(json.dumps(add_workflow(name, scenario, status, commit, Path(source)), indent=2))
        return 0
    example = f"bench folder, e.g. runs/bench/{DEFAULT_BENCH}"
    parser.add_argument("bench_dir", type=Path, help=example)
    entries = build(parser.parse_args().bench_dir)
    print(json.dumps(entries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
