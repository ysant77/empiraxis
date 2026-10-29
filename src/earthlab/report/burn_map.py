"""Quick-look map of one month of a case: MCD64A1 burned pixels, cells without valid data,
and FIRMS detections drawn as context. The map shows the tool's pixels; it is not a claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

from earthlab.cases.loader import CaseFile
from earthlab.cases.models import BoundingBox
from earthlab.data.firms import detections
from earthlab.data.mcd64a1 import load_month
from earthlab.report.evidence import firms_asset_id
from earthlab.science.burned_area import QA_POLICY_FILE, QaPolicy, classify, load_qa_policies
from earthlab.tools.burned_area_tools import mcd64a1_asset_id


@dataclass(frozen=True)
class MapPoints:
    burned_lon: np.ndarray
    burned_lat: np.ndarray
    no_data_lon: np.ndarray
    no_data_lat: np.ndarray
    firms_lon: np.ndarray
    firms_lat: np.ndarray


def burned_points(case_file: CaseFile, root: Path, month: str, policy: QaPolicy) -> MapPoints:
    """Pixel centres of burned and of land-without-valid-data cells, and FIRMS points."""
    case = case_file.case
    assert case.data_dir is not None
    assert case.area.bbox is not None
    folder, box = root / case.data_dir, case.area.bbox
    raster = load_month(folder, f"{mcd64a1_asset_id(case_file)}.manifest.json", month)
    c = classify(raster, box, load_qa_policies(root / QA_POLICY_FILE)[policy])
    no_data = c.land & ~c.valid
    firms_id = firms_asset_id(case_file)
    points = [] if firms_id is None else detections(folder, f"{firms_id}.manifest.json", box, month)
    fire = np.array(points).reshape(-1, 2)
    return MapPoints(
        burned_lon=c.lon[c.burned],
        burned_lat=c.lat[c.burned],
        no_data_lon=c.lon[no_data],
        no_data_lat=c.lat[no_data],
        firms_lon=fire[:, 0],
        firms_lat=fire[:, 1],
    )


def _frame(ax: Any, box: BoundingBox, title: str) -> None:
    """Study-box outline, extent, equal aspect and labels."""
    ax.add_patch(
        Rectangle(
            (box.min_lon, box.min_lat),
            box.max_lon - box.min_lon,
            box.max_lat - box.min_lat,
            fill=False,
            linewidth=1,
            edgecolor="#333333",
        )
    )
    ax.set_xlim(box.min_lon - 0.05, box.max_lon + 0.05)
    ax.set_ylim(box.min_lat - 0.05, box.max_lat + 0.05)
    ax.set_aspect("equal")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(title, fontsize=9)


def burn_map(case_file: CaseFile, root: Path, month: str, policy: QaPolicy, out: Path) -> Path:
    pts = burned_points(case_file, root, month, policy)
    box = case_file.case.area.bbox
    assert box is not None
    fig, ax = plt.subplots(figsize=(6.4, 6.4), dpi=110)
    ax.scatter(
        pts.no_data_lon,
        pts.no_data_lat,
        s=3,
        marker="s",
        c="#c9c9c9",
        linewidths=0,
        label="land without valid data (not counted)",
    )
    ax.scatter(
        pts.burned_lon,
        pts.burned_lat,
        s=3,
        marker="s",
        c="#b2372b",
        linewidths=0,
        label=f"MCD64A1 burned, QA {policy.value} ({len(pts.burned_lon)} px)",
        zorder=3,  # burned pixels above the FIRMS context points
    )
    ax.scatter(
        pts.firms_lon,
        pts.firms_lat,
        s=2,
        marker=".",
        c="#d99a00",
        alpha=0.6,
        label=f"FIRMS detections ({len(pts.firms_lon)}): context, not burned area",
    )
    _frame(ax, box, f"{case_file.case.case_id}, {month} (UTC month)")
    ax.legend(fontsize=7, loc="lower left", markerscale=3)
    fig.text(0.01, 0.01, "500 m pixel centres. Mapped burned area, not forest loss.", fontsize=7)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return out
