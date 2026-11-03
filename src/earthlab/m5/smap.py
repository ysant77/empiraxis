"""SMAP L3 (SPL3SMP, 36 km) reader: soil moisture inside a box, with QA kept visible.

A cell has a retrieval when `soil_moisture` is not the fill value. A cell is quality-screened
when, in addition, bit 0 of `retrieval_qual_flag` is 0 (recommended quality). Cells that fail
stay missing: they are never set to zero and never interpolated. The AM pass (about 06:00 local
solar time) and the PM pass (about 18:00) are separate groups; PM variables end in `_pm`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import h5py
import numpy as np
from numpy.typing import NDArray

from earthlab.cases.models import BoundingBox

FILL = -9999.0
RECOMMENDED_BIT = 1  # bit 0 of retrieval_qual_flag: 0 = recommended quality, 1 = not
PASSES = {
    "AM": ("Soil_Moisture_Retrieval_Data_AM", ""),
    "PM": ("Soil_Moisture_Retrieval_Data_PM", "_pm"),
}


@dataclass(frozen=True)
class PassStats:
    pass_name: str
    cells_in_box: int
    retrieved: int
    recommended: int
    flag_values: dict[int, int] = field(default_factory=dict)
    vegetation_water_content_mean: float | None = None
    soil_moisture_screened: NDArray[np.float64] = field(default_factory=lambda: np.empty(0))

    def as_dict(self) -> dict[str, Any]:
        return {
            "pass": self.pass_name, "cells_in_box": self.cells_in_box,
            "retrieved": self.retrieved, "recommended_quality": self.recommended,
            "flag_values": {str(k): v for k, v in sorted(self.flag_values.items())},
            "vegetation_water_content_mean_kg_m2": self.vegetation_water_content_mean,
        }  # fmt: skip


def box_mask(lat: NDArray[Any], lon: NDArray[Any], box: BoundingBox) -> NDArray[np.bool_]:
    """Cells whose centre lies in the box. Fill coordinates (-9999) are outside every box."""
    return np.asarray((lon >= box.min_lon) & (lon <= box.max_lon)
                      & (lat >= box.min_lat) & (lat <= box.max_lat))  # fmt: skip


def pass_stats(h5: h5py.File, which: str, box: BoundingBox) -> PassStats:
    group_name, sfx = PASSES[which]
    g = h5[group_name]
    lat, lon = g[f"latitude{sfx}"][:], g[f"longitude{sfx}"][:]
    sm = g[f"soil_moisture{sfx}"][:].astype(np.float64)
    flag = g[f"retrieval_qual_flag{sfx}"][:]
    vwc = g[f"vegetation_water_content{sfx}"][:].astype(np.float64)
    inside = box_mask(lat, lon, box)
    retrieved = inside & (sm != FILL)
    good = retrieved & ((flag & RECOMMENDED_BIT) == 0)
    screened = np.where(good, sm, np.nan)[inside]
    veg = vwc[retrieved & (vwc != FILL)]
    return PassStats(
        pass_name=which, cells_in_box=int(inside.sum()), retrieved=int(retrieved.sum()),
        recommended=int(good.sum()), flag_values=dict(Counter(int(v) for v in flag[retrieved])),
        vegetation_water_content_mean=float(veg.mean()) if veg.size else None,
        soil_moisture_screened=screened,
    )  # fmt: skip


def granule_stats(path: Path, box: BoundingBox) -> list[PassStats]:
    with h5py.File(path, "r") as h5:
        return [pass_stats(h5, which, box) for which in PASSES]
