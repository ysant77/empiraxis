"""Approval-gated acquisition of one case asset, with a manifest for every pinned file.

Order: check the study-area approval, check the download approval for the asset and its
expected size, fetch, enforce the byte cap on the real stream, hash, and write a
manifest that records source, licence, retrieval time, grid and reference statistics.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from earthlab.acquire import era5, firms, mcd64a1
from earthlab.acquire.gate import authorize, write_capped
from earthlab.cases.loader import CaseFile
from earthlab.cases.models import ApprovalAction, HumanApproval, RequestScope, SourceAsset

FIRMS_ROW_BYTES = 120  # expected upper bound per detection row, for the size request
FIRMS_EXPECTED_ROWS = 20_000


def _months(asset: SourceAsset) -> list[tuple[date, date]]:
    first = asset.coverage.start.date()
    end = asset.coverage.end.date()
    months: list[tuple[date, date]] = []
    while first < end:
        nxt = (first.replace(day=1) + timedelta(days=32)).replace(day=1)
        months.append((first, min(nxt, end)))
        first = nxt
    return months


def _gate(
    approvals: list[HumanApproval],
    case_file: CaseFile,
    asset: SourceAsset,
    expected_bytes: int,
    request: RequestScope | None = None,
) -> HumanApproval:
    case_id = case_file.case.case_id
    authorize(
        approvals, ApprovalAction.CONFIRM_STUDY_AREA, case_id, asset_id=None, request_bytes=None
    )
    return authorize(
        approvals,
        ApprovalAction.DOWNLOAD,
        case_id,
        asset_id=asset.asset_id,
        request_bytes=expected_bytes,
        request=request or _scope_of(asset),
    )


def _scope_of(
    asset: SourceAsset, variables: tuple[str, ...] = (), levels: tuple[int, ...] = ()
) -> RequestScope:
    """What a download of this asset fetches, for a scoped approval to check."""
    assert asset.extent is not None
    return RequestScope(
        product=asset.product,
        extent=asset.extent,
        start=asset.coverage.start,
        end=asset.coverage.end,
        variables=variables,
        pressure_levels_hpa=levels,
    )


def _manifest(
    asset: SourceAsset, approval: HumanApproval, files: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "asset_id": asset.asset_id,
        "product": asset.product,
        "version": asset.version,
        "provider": asset.provider,
        "source_url": asset.url,
        "licence": asset.licence,
        "licence_url": asset.licence_url,
        "crs": asset.crs,
        "extent": asset.extent.model_dump() if asset.extent else None,
        "coverage": asset.coverage.model_dump(mode="json"),
        "approval_id": approval.approval_id,
        "retrieved_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": files,
        "total_bytes": sum(f["bytes"] for f in files),
    }


def acquire_mcd64a1(
    case_file: CaseFile, asset_id: str, approvals: list[HumanApproval], out_dir: Path, ee: Any
) -> dict[str, Any]:
    asset = case_file.assets[asset_id]
    assert asset.extent is not None
    months = _months(asset)
    expected = len(months) * 300 * 300 * len(mcd64a1.BANDS) * 2 + 100_000
    approval = _gate(approvals, case_file, asset, expected)
    assert approval.max_bytes is not None
    budget = approval.max_bytes
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for first, end in months:
        image = mcd64a1.month_image(ee, first, end)
        grid = mcd64a1.native_grid(image)
        reference = mcd64a1.reference_stats(ee, image, asset.extent, grid)
        url = mcd64a1.download_url(ee, image, asset.extent, grid)
        path = out_dir / f"mcd64a1_{first:%Y_%m}.tif"
        with httpx.stream("GET", url, timeout=300.0, follow_redirects=True) as resp:
            resp.raise_for_status()
            sha, size = write_capped(resp.iter_bytes(), path, budget)
        budget -= size
        files.append(
            {
                "file": path.name,
                "month": f"{first:%Y-%m}",
                "sha256": sha,
                "bytes": size,
                "grid": grid,
                "fill_value": mcd64a1.FILL,
                "fill_meaning": "masked in Earth Engine: unburned or unmapped; QA bits decide",
                "bands": list(mcd64a1.BANDS),
                "reference": reference,
            }
        )
    return _manifest(asset, approval, files)


def acquire_firms(
    case_file: CaseFile,
    asset_id: str,
    approvals: list[HumanApproval],
    out_dir: Path,
    client_factory: Callable[[], httpx.Client] = httpx.Client,
) -> dict[str, Any]:
    asset = case_file.assets[asset_id]
    assert asset.extent is not None
    approval = _gate(approvals, case_file, asset, FIRMS_ROW_BYTES * FIRMS_EXPECTED_ROWS)
    assert approval.max_bytes is not None
    key = os.environ.get("FIRMS_API_KEY", "")
    if not key:
        raise RuntimeError("FIRMS_API_KEY is not set")
    source = asset.product.split("/", 1)[1]
    start, end = asset.coverage.start.date(), asset.coverage.end.date()
    with client_factory() as client:
        parts = firms.fetch_parts(key, source, asset.extent, start, end, client)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"firms_{source.lower()}_{start:%Y_%m}_{end:%Y_%m}.csv"
    sha, size = write_capped(firms.joined_csv(parts), path, approval.max_bytes)
    rows = sum(1 for _ in path.open(encoding="utf-8")) - 1
    files = [
        {
            "file": path.name,
            "sha256": sha,
            "bytes": size,
            "rows": rows,
            "requests": len(firms.chunks(start, end)),
        }
    ]
    return _manifest(asset, approval, files)


def acquire_era5(
    case_file: CaseFile,
    asset_id: str,
    approvals: list[HumanApproval],
    out_dir: Path,
    client_factory: Callable[[], era5.CdsClient] = era5.client_from_config,
    variables: tuple[str, ...] | None = None,
    levels: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    """The approved ERA5 H1 request for one asset, month by month, under one byte cap."""
    asset = case_file.assets[asset_id]
    assert asset.extent is not None
    dataset = era5.dataset_of(asset.product)
    variables = era5.H1_VARIABLES[dataset] if variables is None else variables
    levels = era5.H1_LEVELS[dataset] if levels is None else levels
    start, end = asset.coverage.start, asset.coverage.end
    era5.check_h1(dataset, variables, levels, asset.extent, start, end)
    hours = int((end - start) / timedelta(hours=1))
    expected = era5.expected_bytes(variables, levels, asset.extent, hours)
    approval = _gate(approvals, case_file, asset, expected, _scope_of(asset, variables, levels))
    assert approval.max_bytes is not None
    client = client_factory()
    out_dir.mkdir(parents=True, exist_ok=True)
    budget, files = approval.max_bytes, []
    for month, request in era5.monthly_requests(variables, levels, asset.extent, start, end):
        path = out_dir / era5.month_file(dataset, month)
        sha, size = era5.fetch_month(client, dataset, request, path, budget)
        budget -= size
        files.append(
            {
                "file": path.name,
                "month": f"{month:%Y-%m}",
                "sha256": sha,
                "bytes": size,
                "dataset": dataset,
                "request": request,
            }
        )
    return _manifest(asset, approval, files)


def write_manifest(manifest: dict[str, Any], out_dir: Path) -> Path:
    path = out_dir / f"{manifest['asset_id']}.manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path
