"""Run rung H1 (Amendment 5) for 2015 and 2016 in Stage P and write the record.

Usage: uv run python scripts/m5_run_h1.py DATA_ROOT HAZE2015_RUN_FOLDER
Output: docs/m5/results/m5_h1_stage_p.json
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from earthlab.digest import file_digest
from earthlab.haze import ablation_features as F
from earthlab.m5 import strict_json as sj
from earthlab.m5.ladder_data import build_season, load_open_grid
from earthlab.m5.ladder_h1 import stage_p_h1


def main() -> int:
    data, haze = Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()
    grid = load_open_grid(Path("data/nea/Historical1hrPM2.5.csv"))
    out: dict[str, object] = {"protocol_id": "m5-protocol-1", "amendment": 5}
    folders = {
        2015: (haze, haze / "firms"),
        2016: (data / "season/2016", data / "season/2016/firms"),
    }
    inputs = {}
    for year, (met_folder, firms) in folders.items():
        start, met = F.load_met(met_folder)
        out[str(year)] = stage_p_h1(build_season(grid, year, firms), start, met)
        for name in ("extract_10m.json", "extract_850hpa.json"):
            inputs[f"{year}/{name}"] = file_digest(met_folder / name)
    out["inputs"] = inputs
    out["computed_at_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    dest = Path("docs/m5/results/m5_h1_stage_p.json")
    dest.write_text(sj.dumps(out, indent=2, sort_keys=True, default=float) + "\n")
    for year in ("2015", "2016"):
        r = out[year]
        print(year, r["scored_rows"], r["mae"], r["paired"])  # type: ignore[index]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
