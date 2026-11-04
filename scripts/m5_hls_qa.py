"""HLS L30 quality statistics and an MCD64A1 contrast for the Kalimantan pilot pair.

Usage: uv run python -I scripts/m5_hls_qa.py DATA_ROOT   (reads local files only)
Output: docs/m5/qa/hls_qa.json
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

from earthlab.cases.models import BoundingBox
from earthlab.data.mcd64a1 import load_month
from earthlab.m5 import masks
from earthlab.m5 import strict_json as sj
from earthlab.m5.contrast import burn_contrast
from earthlab.m5.hls import FMASK_FILL, read_fmask, read_reflectance
from earthlab.science.burned_area import classify

BOX = BoundingBox(min_lon=113.8, min_lat=-3.2, max_lon=114.8, max_lat=-2.0)
KAL = Path("data/kalimantan-2015")
MANIFEST = "mcd64a1-061-kalimantan-2015.manifest.json"
PRE, POST = ("2015256T022818", 256), ("2015288T022823", 288)
TILE = "T50MKB"
_ADJ_SHADOW = masks.FMASK_ADJACENT | masks.FMASK_SHADOW


def _name(stamp: str, band: str) -> str:
    return f"HLS.L30.{TILE}.{stamp}.v2.0.{band}.tif"


def _qa(fmask: np.ndarray) -> dict[str, float]:
    n = len(fmask)
    ok = fmask != FMASK_FILL
    f = np.where(ok, fmask, 0).astype(np.uint8)
    aer = masks.hls_aerosol_level(f)
    return {
        "pixels": n, "no_data": float((~ok).mean()),
        "clear_land": float((masks.hls_clear_land(f) & ok).mean()),
        "cloud": float(((f & masks.FMASK_CLOUD) > 0)[ok].mean()),
        "adjacent_or_shadow": float(((f & _ADJ_SHADOW) > 0)[ok].mean()),
        "water": float(((f & masks.FMASK_WATER) > 0)[ok].mean()),
        **{f"aerosol_level_{k}": float((aer[ok] == k).mean()) for k in range(4)},
    }  # fmt: skip


def main() -> int:
    root = Path(sys.argv[1]).expanduser() / "raw" / "hlsl30-v2.0"
    sep, octo = (load_month(KAL, MANIFEST, m) for m in ("2015-09", "2015-10"))
    cs, co = classify(sep, BOX), classify(octo, BOX)
    inside = cs.inside
    lon, lat = cs.lon[inside], cs.lat[inside]
    out: dict[str, Any] = {"tile": TILE, "dates": {"pre": "2015-09-13", "post": "2015-10-15"}}
    clear: dict[str, np.ndarray] = {}
    nbr: dict[str, np.ndarray] = {}
    for label, (stamp, _) in (("pre", PRE), ("post", POST)):
        fm = read_fmask(root / _name(stamp, "Fmask")).sample(lon, lat)
        fm_u8 = np.where(np.isnan(fm), FMASK_FILL, fm).astype(np.uint8)
        out[label] = _qa(fm_u8)
        clear[label] = masks.hls_clear_land(fm_u8) & (fm_u8 != FMASK_FILL)
        nir = read_reflectance(root / _name(stamp, "B05")).sample(lon, lat)
        swir = read_reflectance(root / _name(stamp, "B07")).sample(lon, lat)
        nbr[label] = masks.nbr(nir, swir, clear[label])
    d = masks.dnbr(nbr["pre"], nbr["post"])
    s_burn, o_burn = sep.bands["BurnDate"][inside], octo.bands["BurnDate"][inside]
    in_window = ((s_burn > PRE[1]) & (s_burn <= 273) & cs.valid[inside]) | (
        (o_burn >= 274) & (o_burn <= POST[1]) & co.valid[inside])  # fmt: skip
    control = cs.valid[inside] & co.valid[inside] & (s_burn <= 0) & (o_burn <= 0)
    out["mcd64a1_window"] = {"burned_window_doy": [PRE[1] + 1, POST[1]]}
    out["both_dates_clear_fraction_of_box_pixels"] = float((clear["pre"] & clear["post"]).mean())
    out["dnbr_contrast"] = burn_contrast(d, in_window, control)
    out["notes"] = [
        "MCD64A1 labels are another satellite product, not ground truth.",
        "Provider cloud_cover does not measure smoke haze; Fmask is used here.",
    ]
    dest = Path("docs/m5/qa/hls_qa.json")
    dest.write_text(sj.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(sj.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
