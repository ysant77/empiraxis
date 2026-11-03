"""Run the M5 ladder under protocol m5-protocol-1 and write the result record.

Usage: uv run python scripts/m5_run_ladder.py DATA_ROOT HAZE2015_RUN_FOLDER STAGE
STAGE is `p` (pilot seasons, blocked scheme) or `t` (train 2015-2018, score 2019).
NEA labels from 2024 on are removed on load. The record carries every input digest.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from earthlab.digest import file_digest
from earthlab.m5 import ladder as L
from earthlab.m5.ladder_data import Season, build_season, load_open_grid

NEA = Path("data/nea/Historical1hrPM2.5.csv")
OUT = Path("docs/m5/results")


def firms_folder(data_root: Path, haze2015: Path, year: int) -> Path:
    return haze2015 / "firms" if year == 2015 else data_root / "season" / str(year) / "firms"


def digests(folders: list[Path]) -> dict[str, str]:
    files = [NEA] + [p for f in folders for p in sorted(f.glob("box-*/*.csv"))]
    return {str(p.relative_to(p.parents[3]) if p != NEA else p): file_digest(p) for p in files}


def main() -> int:
    data_root, haze2015, stage = (
        Path(sys.argv[1]).expanduser(),
        Path(sys.argv[2]).expanduser(),
        sys.argv[3],
    )
    grid = load_open_grid(NEA)
    years = [2015, 2016] if stage == "p" else [2015, 2016, 2017, 2018, 2019]
    folders = {y: firms_folder(data_root, haze2015, y) for y in years}
    seasons = {y: build_season(grid, y, folders[y]) for y in years}
    record: dict[str, Any] = {"protocol_id": "m5-protocol-1", "stage": stage,
                              "computed_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                              "inputs": digests(list(folders.values()))}  # fmt: skip
    if stage == "p":
        for y in years:
            t0 = time.perf_counter()
            record[str(y)] = L.stage_p(seasons[y])
            record[str(y)]["wall_seconds"] = time.perf_counter() - t0
    else:
        train = [seasons[y] for y in (2015, 2016, 2017, 2018)]
        test: Season = seasons[2019]
        out = L.stage_t(train, test)
        record["2019"] = L.summarise(L.score_rows(test, out["preds"]))
        record["2019"]["cost_seconds"] = out["cost_seconds"]
        paired, elev = record["2019"]["paired"], record["2019"]["elevated_paired"]
        record["2019"]["labels"] = {k: L.label(v, elev.get(k), record["2019"]["scored_rows"])
                                    for k, v in paired.items()}  # fmt: skip
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"m5_ladder_stage_{stage}.json").write_text(
        json.dumps(
            record,
            indent=2,
            sort_keys=True,
            default=lambda o: float(o) if isinstance(o, np.floating) else str(o),
        )
        + "\n"
    )
    print(
        json.dumps(
            {k: record[k] for k in record if k.isdigit()}, indent=1, sort_keys=True, default=str
        )[:6000]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
