"""Run the 2015 haze feature ablation and save its record with input digests.

Usage: uv run python scripts/run_haze_ablation.py <haze-2015 run folder>
The folder holds extract_10m.json, extract_850hpa.json and firms/box-*/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from earthlab.digest import file_digest
from earthlab.forecast.dataset import load_grid
from earthlab.haze.ablation import run

SOURCE = Path("data/nea/Historical1hrPM2.5.csv")
OUT = Path("docs/evidence/haze-2015-ablation.json")


def main() -> int:
    folder = Path(sys.argv[1]).expanduser()
    grid, _ = load_grid(SOURCE)
    record = run(grid, folder)
    inputs = [SOURCE, folder / "extract_10m.json", folder / "extract_850hpa.json",
              *sorted((folder / "firms").glob("box-*/*.csv"))]  # fmt: skip
    record["inputs"] = {p.name: file_digest(p) for p in inputs}
    OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("scored_rows", "mae", "elevated_mae", "paired")},
                     indent=2))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
