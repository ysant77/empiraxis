"""S4: a deterministic gate for a request to segment burn scars with a pretrained model.

The gate reads facts that code measured. It never runs the model and never reads the weights.
It adds checks to `gates.check_segmentation`: band order, CRS, coverage, approval of the
weights, storage and compute. MCD64A1 is a mapped product, so it is never a reference mask.
HLS is multispectral. When a check fails, the gate lists what is missing, how many bytes the
smallest fix needs, and the route to a human decision.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from earthlab.cases.models import BoundingBox
from earthlab.contracts import Strict
from earthlab.harness import gates
from earthlab.harness.contracts import DatasetProfileV1
from earthlab.harness.suitability import Permission

MIN_COVERAGE = 0.8
MIN_FREE_FACTOR = 1.2
MIN_RAM_BYTES = 8_000_000_000
CHIP_PIXELS = 512
BYTES_PER_SAMPLE = 2
ROUTE = ("data_specialist", "geospatial_lead", "product_manager", "human")
Outcome = Literal["authorized", "request_resources", "refused"]
Device = Literal["cpu", "mps", "cuda"]
_PRODUCT_LABELS = ("mcd64a1", "firms", "modis burned")


class ReferenceMasks(Strict):
    """Labels for scoring a segmentation. They must not come from the product under test."""

    present: bool
    source: str = Field(default="", max_length=200)
    derived_from: tuple[str, ...] = ()


class Imagery(Strict):
    bands: tuple[str, ...] = ()
    crs: str | None = None
    resolution_m: float | None = Field(default=None, gt=0)
    coverage_fraction: float | None = Field(default=None, ge=0, le=1)
    hyperspectral: bool = False


class Weights(Strict):
    asset_id: str
    local_state: Literal["verified", "unverified", "absent"]
    permission: Permission


class Resources(Strict):
    free_disk_bytes: int = Field(ge=0)
    needed_bytes: int = Field(ge=0)
    ram_bytes: int = Field(ge=0)
    device: Device


class SegmentationRequestV1(Strict):
    schema_version: Literal["1"] = "1"
    request_id: str
    question: str = Field(max_length=300)
    aoi: BoundingBox
    masks: ReferenceMasks
    imagery: Imagery
    weights: Weights
    resources: Resources


class Need(Strict):
    item: str
    estimated_bytes: int | None = None
    detail: str = ""


class SegmentationGateV1(Strict):
    schema_version: Literal["1"] = "1"
    request_id: str
    outcome: Outcome
    refusals: tuple[gates.Refusal, ...] = ()
    needs: tuple[Need, ...] = ()
    alternatives: tuple[str, ...] = ()
    route: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def chip_bytes(chips: int, bands: int = 6) -> int:
    """Bytes of `chips` windows of 512 x 512 pixels at 16 bits a sample."""
    return chips * CHIP_PIXELS * CHIP_PIXELS * bands * BYTES_PER_SAMPLE


def _profile(req: SegmentationRequestV1) -> DatasetProfileV1:
    masks = req.masks
    independent = masks.present and not _from_product(masks)
    coverage = req.imagery.coverage_fraction
    return DatasetProfileV1(
        sources=(), variable="burn_scar_reflectance", unit="1", usable_rows=1,
        missing_fraction=1 - (coverage or 0.0), labels_present=independent,
        label_provenance="independent reference mask" if independent else "",
        granularity="scene", resolution_m=req.imagery.resolution_m, bands=req.imagery.bands,
    )  # fmt: skip


def _from_product(masks: ReferenceMasks) -> bool:
    text = " ".join((masks.source, *masks.derived_from)).lower()
    return any(label in text for label in _PRODUCT_LABELS)


def _extra(req: SegmentationRequestV1) -> list[gates.Refusal]:
    out = []
    bands, img = req.imagery.bands, req.imagery
    if img.hyperspectral:
        out.append(gates.Refusal(gates.Code.INCOMPATIBLE_INPUTS, "HLS is multispectral"))
    present = tuple(b for b in gates.HLS_BANDS if b in bands)
    if present and tuple(b for b in bands if b in gates.HLS_BANDS) != present:
        out.append(gates.Refusal(gates.Code.INCOMPATIBLE_INPUTS, "band order differs from HLS"))
    if len(bands) != len(set(bands)):
        out.append(gates.Refusal(gates.Code.INCOMPATIBLE_INPUTS, "a band appears twice"))
    if not img.crs:
        out.append(gates.Refusal(gates.Code.INCOMPATIBLE_INPUTS, "the CRS is not stated"))
    if img.coverage_fraction is None or img.coverage_fraction < MIN_COVERAGE:
        detail = f"coverage {img.coverage_fraction} is below {MIN_COVERAGE}"
        out.append(gates.Refusal(gates.Code.NO_USABLE_DATA, detail))
    if _from_product(req.masks):
        detail = "MCD64A1 is not ground truth for a model that learns from it"
        out.append(gates.Refusal(gates.Code.MISSING_LABELS, detail))
    return out


def _resource_refusals(req: SegmentationRequestV1) -> list[gates.Refusal]:
    out, w, r = [], req.weights, req.resources
    if w.local_state != "verified" or w.permission != "covered_signed":
        detail = f"{w.asset_id}: file {w.local_state}, permission {w.permission}"
        out.append(gates.Refusal(gates.Code.UNSUPPORTED_METHOD, detail))
    if r.free_disk_bytes < r.needed_bytes * MIN_FREE_FACTOR:
        out.append(gates.Refusal(gates.Code.OVER_BUDGET, "not enough free storage"))
    if r.ram_bytes < MIN_RAM_BYTES:
        out.append(gates.Refusal(gates.Code.OVER_BUDGET, "not enough memory for inference"))
    return out


def _needs(req: SegmentationRequestV1, refusals: list[gates.Refusal]) -> list[Need]:
    needs = []
    codes = {r.code for r in refusals}
    if gates.Code.INCOMPATIBLE_INPUTS in codes or gates.Code.NO_USABLE_DATA in codes:
        size = chip_bytes(2)
        text = "six-band HLS for the task area: one 512 x 512 window before and one after"
        needs.append(Need(item=text, estimated_bytes=size, detail="run an availability query"))
    if gates.Code.MISSING_LABELS in codes:
        detail = "independent masks, such as manual or higher-resolution labels"
        needs.append(Need(item="reference burn-scar masks", detail=detail))
    if gates.Code.UNSUPPORTED_METHOD in codes:
        needs.append(Need(item=f"signed approval record for {req.weights.asset_id}"))
    return needs


def gate(req: SegmentationRequestV1) -> SegmentationGateV1:
    """Authorize, ask for resources, or refuse. A model cannot change the result."""
    refusals = [*gates.check_segmentation(_profile(req)), *_extra(req), *_resource_refusals(req)]
    refusals = list({(r.code, r.detail): r for r in refusals}.values())
    if not refusals:
        return SegmentationGateV1(request_id=req.request_id, outcome="authorized")
    hard = req.imagery.hyperspectral
    alternatives = (
        "MCD64A1 monthly burned area with its quality gate (already local)",
        "a dNBR threshold on six-band HLS, scored against independent masks",
    )
    return SegmentationGateV1(
        request_id=req.request_id, outcome="refused" if hard else "request_resources",
        refusals=tuple(refusals), needs=tuple(_needs(req, refusals)), alternatives=alternatives,
        route=() if hard else ROUTE,
        notes=("no segmentation score exists: nothing was run",),
    )  # fmt: skip


def resource_need(item: Need, granule_url: str | None, asset: str) -> dict[str, Any]:
    """The dict that `run_request` takes. It needs a resolved URL, or it asks for input."""
    if granule_url is None or item.estimated_bytes is None:
        raise ValueError("no resolved granule URL: run the availability query first")
    return {
        "url": granule_url, "asset": asset, "max_bytes": item.estimated_bytes,
        "content_types": ["image/tiff"], "license_terms": "NASA Earth science data",
        "credential_name": "EARTHDATA_TOKEN",
    }  # fmt: skip
