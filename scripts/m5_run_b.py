"""Run M5-B under protocol m5-protocol-b-1 and write docs/m5/results/m5_b_v1.json.

Usage: uv run python scripts/m5_run_b.py DATA_ROOT HAZE2015_RUN_FOLDER
Needs FIRMS and ERA5 extracts for 2015 to 2019. A season with missing inputs stops the run.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from earthlab.haze import ablation_features as F
from earthlab.m5 import assoc_data as D
from earthlab.m5 import transport_b as T
from earthlab.m5.assoc import holm
from earthlab.m5.ladder_data import load_open_grid

YEARS = (2015, 2016, 2017, 2018, 2019)
BOXES = ("box-a", "box-b", "box-c")
DRAWS, RESAMPLES, SEED, BLOCK = 9999, 2000, 7, 7


def paths(data: Path, haze: Path, year: int) -> tuple[Path, Path, Path]:
    base = haze if year == 2015 else data / "season" / str(year)
    firms = haze / "firms" if year == 2015 else base / "firms"
    return firms, base / "extract_850hpa.json", base / "extract_10m.json"


def season_inputs(grid: Any, data: Path, haze: Path, year: int) -> dict[str, Any]:
    firms_dir, e850, e10 = paths(data, haze, year)
    firms = F.load_firms(firms_dir)
    win = T.day_window()
    out: dict[str, Any] = {"outcome": T.next_day_change(D.daily_outcome(grid, year))[win]}
    rain = np.mean([D.met_daily(e10, b, year, "precip_mm") for b in BOXES], axis=0)[win]
    out["wet"] = rain >= np.nanmedian(rain)
    for b in BOXES:
        fire = D.fire_daily(firms[f"{b}/t"], year)[win]
        out[b] = {
            "real": fire * T.sector_share(e850, b, year, 0.0)[win],
            "neg": fire * T.sector_share(e850, b, year, 180.0)[win],
        }
    return out


def test_box(box: str, seasons: list[dict[str, Any]], idx: Any) -> dict[str, Any]:
    ys = [s["outcome"] for s in seasons]
    real = [s[box]["real"] for s in seasons]
    neg = [s[box]["neg"] for s in seasons]
    chosen = T.pick_lead(real)
    k = chosen["k"]
    controls = {"negative_corridor": neg}
    if k is not None:
        controls["lead"] = [T.lead(r, k) for r in real]
    r_draws = T.boot_rho(real, ys, idx)
    out: dict[str, Any] = {
        "rho": T.pooled_rho(real, ys),
        "ci": T.interval(r_draws),
        "p_shift": T.shift_p(real, ys, DRAWS, SEED),
        "lead": chosen,
        "controls": {},
    }
    for name, series in controls.items():
        c_draws = T.boot_rho(series, ys, idx)
        out["controls"][name] = {
            "rho": T.pooled_rho(series, ys),
            "ci": T.interval(c_draws),
            "contrast_ci": T.interval(r_draws - c_draws),
        }
    dry = [np.where(s["wet"], np.nan, y) for s, y in zip(seasons, ys, strict=True)]
    out["dry_days"] = {"rho": T.pooled_rho(real, dry), "ci": T.interval(T.boot_rho(real, dry, idx))}
    return out


def main() -> int:
    data, haze = Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()
    grid = load_open_grid(Path("data/nea/Historical1hrPM2.5.csv"))
    seasons = [season_inputs(grid, data, haze, y) for y in YEARS]
    idx = T.boot_indices([len(s["outcome"]) for s in seasons], BLOCK, RESAMPLES, SEED)
    results = {b: test_box(b, seasons, idx) for b in BOXES}
    adj = holm({b: r["p_shift"] for b, r in results.items()})
    for b, r in results.items():
        r["p_holm"] = adj[b]
        contrasts = {n: tuple(c["contrast_ci"]) for n, c in r["controls"].items()}
        needed = len(contrasts) == 2
        r["label"] = T.label(r["rho"], adj[b], contrasts if needed else {})
    record = {"protocol_id": "m5-protocol-b-1", "seasons": list(YEARS), "draws": DRAWS,
              "resamples": RESAMPLES, "tests": results,
              "computed_at_utc": datetime.now(UTC).isoformat(timespec="seconds")}  # fmt: skip
    Path("docs/m5/results/m5_b_v1.json").write_text(
        json.dumps(record, indent=1, sort_keys=True, default=float) + "\n"
    )
    for b, r in results.items():
        print(b, round(r["rho"], 3), r["ci"], "p", r["p_shift"], "holm", r["p_holm"], r["label"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
