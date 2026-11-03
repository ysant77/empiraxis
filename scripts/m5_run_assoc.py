"""Experiment A under protocol m5-protocol-1: daily association, null and Holm per season.

Usage: uv run python scripts/m5_run_assoc.py DATA_ROOT HAZE2015_RUN_FOLDER
Needs ERA5 extracts for each season (2016: DATA_ROOT/season/2016/extract_*.json, made by
scripts/m5_era5_extract.py). Output: docs/m5/results/m5_assoc_v1.json
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from earthlab.haze import ablation_features as F
from earthlab.m5 import assoc
from earthlab.m5 import assoc_data as D
from earthlab.m5.ladder_data import load_open_grid

CFG = yaml.safe_load(Path("config/m5/protocol-v1.yaml").read_text())["experiment_a"]
BOXES = ("box-a", "box-b", "box-c")
OFFSET = 3  # protocol window starts 4 September: day index 3


def season_paths(data_root: Path, haze2015: Path, year: int) -> tuple[Path, Path, Path]:
    if year == 2015:
        return haze2015 / "firms", haze2015 / "extract_850hpa.json", haze2015 / "extract_10m.json"
    base = data_root / "season" / str(year)
    return base / "firms", base / "extract_850hpa.json", base / "extract_10m.json"


def exposures(firms_dir: Path, e850: Path, e10: Path, year: int) -> dict[str, tuple[Any, int]]:
    """FIRMS exposures always; ERA5 exposures only when both extracts exist."""
    firms = F.load_firms(firms_dir)
    fire = {b: D.fire_daily(firms[f"{b}/t"], year) for b in BOXES}
    out: dict[str, tuple[Any, int]] = {f"fire_{b}": (np.log1p(fire[b]), 1) for b in BOXES}
    out["fire_sum"] = (np.log1p(sum(fire.values())), 1)
    if e850.exists() and e10.exists():
        for b in BOXES:
            out[f"transport850_{b}"] = (D.transport_daily(e850, b, year), 1)
        rain = [D.met_daily(e10, b, year, "precip_mm") for b in BOXES]
        out["rain_mean"] = (np.mean(rain, axis=0), -1)
    return out


def run_season(grid: Any, paths: tuple[Path, Path, Path], year: int) -> dict[str, Any]:
    outcome = D.daily_outcome(grid, year)[OFFSET:]
    results: dict[str, dict[str, Any]] = {}
    signs: dict[str, int] = {}
    for name, (series, sign) in exposures(*paths, year).items():
        for lag in CFG["lags_days"]:
            key = f"{name}@lag{lag}"
            results[key] = assoc.test_pair(outcome, assoc.lagged(series, lag)[OFFSET:], CFG)
            signs[key] = sign
    adj = assoc.holm({k: v["p_shift"] for k, v in results.items()})
    for k, v in results.items():
        v["p_holm"] = adj[k]
        v["label"] = assoc.label(v, signs[k], adj[k])
    return {"valid_outcome_days": int((~np.isnan(outcome)).sum()), "tests": results}


def main() -> int:
    data_root, haze2015 = Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()
    grid = load_open_grid(Path("data/nea/Historical1hrPM2.5.csv"))
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    record: dict[str, Any] = {"protocol_id": "m5-protocol-1", "experiment": "A",
                              "computed_at_utc": stamp}  # fmt: skip
    for year in CFG["seasons"]:
        paths = season_paths(data_root, haze2015, year)
        if paths[0].exists():
            record[str(year)] = run_season(grid, paths, year)
        else:
            record[str(year)] = {"status": "BLOCKED_missing_inputs"}
    out = Path("docs/m5/results/m5_assoc_v1.json")
    out.write_text(json.dumps(record, indent=1, sort_keys=True, default=float) + "\n")
    for year in CFG["seasons"]:
        tests = record[str(year)].get("tests", {})
        sup = [k for k, v in tests.items() if v["label"] == "supported_association"]
        print(year, "tests", len(tests), "supported", sup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
