"""Rebuild the offline replay fixture under examples/replay/ from a development bench run.

Each run is a redacted, re-chained copy of a real Muse Glimmer arm B run that passed:
SB-05 (September, verified) and SB-05b (October, abstained on the coverage gate).
The source bench folder is read only. Held-out sources are refused.

Run with:
  uv run python scripts/make_replay_fixture.py <path to runs/bench/<bench id>>
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from earthlab.events.fixture import LABEL, copy_redacted
from earthlab.events.manifest import write_manifest
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    example = f"bench folder, e.g. runs/bench/{DEFAULT_BENCH}"
    parser.add_argument("bench_dir", type=Path, help=example)
    entries = build(parser.parse_args().bench_dir)
    print(json.dumps(entries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
