"""Read-only burned-area tool for a registered case, and the full case report.

The tool computes one month with science/burned_area.py and attaches the independent
verifier's checks, so a reader sees the value and whether it passed in one place.
Nothing here downloads or approves anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from earthlab.cases.loader import CaseFile
from earthlab.cases.tools import CaseLibrary
from earthlab.contracts import Strict
from earthlab.data.mcd64a1 import load_month, read_manifest
from earthlab.science.burned_area import (
    QA_POLICY_FILE,
    QaPolicy,
    load_qa_policies,
    month_doy_range,
    summarize_month,
)
from earthlab.tools.registry import ToolSpec
from earthlab.verify.burned_area_check import check_month, load_tolerances

BURNED_AREA_TOOL = "burned_area_summary"
METHOD_FILE = Path("config") / "methods" / "mcd64a1_burned_area.yaml"
PRODUCT = "MODIS/061/MCD64A1"


def _asset(case_file: CaseFile) -> str:
    ids = [a.asset_id for a in case_file.assets.values() if a.product == PRODUCT]
    if len(ids) != 1 or case_file.case.data_dir is None:
        raise ValueError(f"{case_file.case.case_id} has no pinned MCD64A1 data folder")
    return ids[0]


def month_report(
    case_file: CaseFile, root: Path, month: str, qa_policy: QaPolicy = QaPolicy.PRIMARY
) -> dict[str, Any]:
    """Tool value, verifier checks and provenance for one month of one case and QA policy."""
    asset_id = _asset(case_file)
    assert case_file.case.data_dir is not None
    assert case_file.case.area.bbox is not None
    data_dir = root / case_file.case.data_dir
    manifest_name = f"{asset_id}.manifest.json"
    tol = load_tolerances(root / METHOD_FILE)
    box = case_file.case.area.bbox
    bits = load_qa_policies(root / QA_POLICY_FILE)[qa_policy]
    raster = load_month(data_dir, manifest_name, month)
    summary = summarize_month(raster, box, tol.min_valid_fraction, bits)
    entry = next(f for f in read_manifest(data_dir / manifest_name)["files"] if f["month"] == month)
    check = check_month(summary, data_dir, entry, box, month_doy_range(month), tol, bits)
    return {
        "case_id": case_file.case.case_id,
        "month": month,
        "qa_policy": qa_policy.value,
        "summary": {**summary.model_dump(), "primary_area_ha": round(summary.primary_area_ha, 1)},
        "check": check.model_dump(),
        "source": {"product": PRODUCT, "file": raster.file, "sha256": raster.sha256},
        "limitations": [
            "Mapped burned area at 500 m; not destroyed trees, forest loss or emissions.",
            "FIRMS hotspot counts are not burned area and are not used here.",
        ],
    }


def case_report(case_file: CaseFile, root: Path) -> list[dict[str, Any]]:
    asset_id = _asset(case_file)
    assert case_file.case.data_dir is not None
    manifest = read_manifest(root / case_file.case.data_dir / f"{asset_id}.manifest.json")
    return [month_report(case_file, root, f["month"]) for f in manifest["files"]]


class BurnedAreaArgs(Strict):
    case_id: str = Field(min_length=1, max_length=80)
    month: str = Field(pattern=r"^\d{4}-\d{2}$", description="UTC calendar month, YYYY-MM.")
    qa_policy: QaPolicy = Field(
        default=QaPolicy.PRIMARY,
        description="Pre-registered QA policy. primary is the base method; full_period, "
        "not_relabeled and strict also drop burned cells flagged by QA bit 2, bit 3 or both. "
        "Use the others only for a quality-mask sensitivity question.",
    )


def burned_area_spec(
    library: CaseLibrary, consulted: list[tuple[str, str]] | None = None
) -> ToolSpec:
    """consulted, when given, records each (case_id, month) the tool answered."""

    def handle(args: BurnedAreaArgs) -> dict[str, Any]:
        report = month_report(library.get(args.case_id), library.root, args.month, args.qa_policy)
        if consulted is not None:
            consulted.append((args.case_id, args.month))
        return report

    return ToolSpec(
        BURNED_AREA_TOOL,
        "Mapped burned area (MCD64A1, quality-filtered) for one month of a registered case, "
        "with valid-data fraction and independent verifier checks. Not hotspot counts.",
        BurnedAreaArgs,
        handle,
    )
