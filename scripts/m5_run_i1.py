"""Run rung I1 for the 2015 season (Stage P, Amendment 4) and write the record.

Usage: uv run python scripts/m5_run_i1.py DATA_ROOT HAZE2015_RUN_FOLDER
Output: docs/m5/results/m5_i1_stage_p_2015.json
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from earthlab.digest import file_digest
from earthlab.m5 import imerg_series as S
from earthlab.m5.ladder_data import build_season, load_open_grid
from earthlab.m5.ladder_i1 import rain_matrix, stage_p_i1


def main() -> int:
    data, haze = Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()
    csv_path = data / "derived" / "imerg_early_corridors.csv"
    grid = load_open_grid(Path("data/nea/Historical1hrPM2.5.csv"))
    season = build_season(grid, 2015, haze / "firms")
    out = stage_p_i1(season, rain_matrix(season, S.load_series(csv_path)))
    out["protocol_id"] = "m5-protocol-1"
    out["amendment"] = 4
    out["computed_at_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    out["inputs"] = {"imerg_early_corridors.csv": file_digest(csv_path)}
    dest = Path("docs/m5/results/m5_i1_stage_p_2015.json")
    dest.write_text(json.dumps(out, indent=2, sort_keys=True, default=float) + "\n")
    print(
        json.dumps({k: out[k] for k in ("scored_rows", "mae", "paired")}, indent=1, default=float)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
