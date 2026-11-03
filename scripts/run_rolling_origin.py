"""Run the rolling-origin ridge search on the train years and save its record."""

from __future__ import annotations

import json
from pathlib import Path

from earthlab.digest import payload_digest
from earthlab.forecast.dataset import load_grid
from earthlab.mlops.rolling import run

SOURCE = Path("data/nea/Historical1hrPM2.5.csv")
OUT = Path("docs/evidence/rolling-origin-ridge-v1.json")


def main() -> int:
    grid, _ = load_grid(SOURCE)
    record = run(grid)
    record["source"] = str(SOURCE)
    record["record_sha256"] = payload_digest(record)
    OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    best = record["search"]["trials"][record["search"]["best_trial"]]
    print(json.dumps({"best": best["config"], "mean_fold_mae": best["validation_score"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
