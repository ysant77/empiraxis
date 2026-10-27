"""Independent verification of a burned-area summary, with pre-registered tolerances.

The verifier does not call the tool's code. It re-reads the pinned bytes, re-derives
each pixel's latitude band from its row, and computes area with a closed-form WGS84
ellipsoid integral (area of a sinusoidal pixel = sx / R * integral of M(phi) N(phi)
over its latitude band), not with pyproj polygons. It then applies the checks in
config/methods/mcd64a1_burned_area.yaml against the tool and the Earth Engine reference.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import tifffile
import yaml
from pydantic import Field

from earthlab.cases.models import BoundingBox
from earthlab.contracts import Strict
from earthlab.digest import file_digest
from earthlab.science.burned_area import MonthSummary

_A = 6378137.0
_F = 1 / 298.257223563
_E2 = _F * (2 - _F)
_R = 6371007.181
_SIMPSON_STEPS = 32


class Tolerances(Strict):
    min_valid_fraction: float = Field(ge=0, le=1)
    per_pixel_area_relative_max: float = Field(gt=0)
    tool_vs_verifier_relative_max: float = Field(gt=0)
    claim_relative_max: float = Field(gt=0)


def load_tolerances(path: Path) -> Tolerances:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Tolerances(
        min_valid_fraction=raw["reporting_gate"]["min_valid_fraction"],
        **{
            k: raw["acceptance"][k]
            for k in (
                "per_pixel_area_relative_max",
                "tool_vs_verifier_relative_max",
                "claim_relative_max",
            )
        },
    )


def _band_area(top_y: float, sx: float, sy: float) -> float:
    """Ellipsoid area of one sinusoidal pixel whose top edge is at northing top_y."""
    lo, hi = (top_y - sy) / _R, top_y / _R
    h = (hi - lo) / _SIMPSON_STEPS

    def mn(phi: float) -> float:
        s = math.sin(phi)
        return _A * _A * (1 - _E2) / (1 - _E2 * s * s) ** 2

    total = mn(lo) + mn(hi)
    total += sum((4 if i % 2 else 2) * mn(lo + i * h) for i in range(1, _SIMPSON_STEPS))
    return sx / _R * total * h / 3


class MonthCheck(Strict):
    month: str
    verifier_burned_pixels: int
    verifier_area_m2: float
    verifier_valid_fraction: float
    ee_burned_pixels: int
    verifier_area_per_pixel_m2: float
    ee_area_per_pixel_m2: float
    allowed_count_difference: int
    c1_count_ok: bool
    c2_per_pixel_area_ok: bool
    c3_tool_vs_verifier_ok: bool
    gate_ok: bool
    passed: bool
    notes: list[str]


def _recount(
    path: Path, entry: dict[str, Any], box: BoundingBox, month_days: tuple[int, int]
) -> tuple[int, float, float]:
    if file_digest(path) != entry["sha256"]:
        raise ValueError(f"{path.name}: hash mismatch")
    with tifffile.TiffFile(path) as tif:
        stack = tif.asarray().astype(np.int64)
        matrix = tif.pages[0].tags["ModelTransformationTag"].value  # type: ignore[union-attr]
    stack = np.moveaxis(stack, 0, -1) if stack.shape[0] == 5 else stack
    sx, x0, sy, y0 = matrix[0], matrix[3], -matrix[5], matrix[7]
    burned = 0
    area = 0.0
    land = valid = 0
    for row in range(stack.shape[0]):
        lat = (y0 - (row + 0.5) * sy) / _R
        if not math.radians(box.min_lat) <= lat <= math.radians(box.max_lat):
            continue
        x_west = math.radians(box.min_lon) * _R * math.cos(lat)
        x_east = math.radians(box.max_lon) * _R * math.cos(lat)
        centres = x0 + (np.arange(stack.shape[1]) + 0.5) * sx
        cols = (centres >= x_west) & (centres <= x_east)
        qa, burn = stack[row, cols, 2], stack[row, cols, 0]
        is_land = (qa >= 0) & (qa % 2 == 1)
        is_valid = is_land & ((qa // 2) % 2 == 1)
        hits = int((is_valid & (burn >= month_days[0]) & (burn <= month_days[1])).sum())
        land, valid, burned = land + int(is_land.sum()), valid + int(is_valid.sum()), burned + hits
        area += hits * _band_area(y0 - row * sy, sx, sy)
    return burned, area, (valid / land if land else 0.0)


def check_month(
    summary: MonthSummary,
    data_dir: Path,
    entry: dict[str, Any],
    box: BoundingBox,
    month_days: tuple[int, int],
    tol: Tolerances,
) -> MonthCheck:
    burned, area, fraction = _recount(data_dir / entry["file"], entry, box, month_days)
    ref = entry["reference"]
    allowed = summary.burned_pixels_near_edge
    c1 = abs(burned - ref["burned_valid_pixels"]) <= allowed and burned == summary.burned_pixels
    ee_per_px = (
        ref["burned_valid_area_m2"] / ref["burned_valid_pixels"]
        if ref["burned_valid_pixels"]
        else 0.0
    )
    own_per_px = area / burned if burned else 0.0
    c2 = burned == 0 or abs(own_per_px - ee_per_px) <= tol.per_pixel_area_relative_max * ee_per_px
    c3 = abs(area - summary.primary_area_m2) <= tol.tool_vs_verifier_relative_max * max(area, 1.0)
    gate = fraction >= tol.min_valid_fraction
    notes = [] if gate else [f"valid fraction {fraction:.3f} is below {tol.min_valid_fraction}"]
    return MonthCheck(
        month=summary.month,
        verifier_burned_pixels=burned,
        verifier_area_m2=round(area, 1),
        verifier_valid_fraction=round(fraction, 6),
        ee_burned_pixels=ref["burned_valid_pixels"],
        verifier_area_per_pixel_m2=round(own_per_px, 2),
        ee_area_per_pixel_m2=round(ee_per_px, 2),
        allowed_count_difference=allowed,
        c1_count_ok=c1,
        c2_per_pixel_area_ok=c2,
        c3_tool_vs_verifier_ok=c3,
        gate_ok=gate,
        passed=c1 and c2 and c3,
        notes=notes,
    )


def claim_verdict(claimed_ha: float, check: MonthCheck, tol: Tolerances) -> tuple[str, str]:
    """supported / contradicted / insufficient_data for a claimed area in hectares."""
    if not check.passed:
        return "not_verified", "the independent checks did not pass"
    if not check.gate_ok:
        return "insufficient_data", "; ".join(check.notes)
    truth_ha = check.verifier_area_m2 / 1e4
    if abs(claimed_ha - truth_ha) <= tol.claim_relative_max * truth_ha:
        return "supported_observation", f"matches the recomputed {truth_ha:.1f} ha"
    return "contradicted", f"recomputed area is {truth_ha:.1f} ha"
