"""S4: the gate for burn-scar segmentation, and the request route to a human. No model runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fake_client import ScriptedClient, call
from suitability_helpers import AOI

from earthlab.harness import gates
from earthlab.harness.segmentation_gate import (
    Imagery,
    Need,
    ReferenceMasks,
    Resources,
    SegmentationRequestV1,
    Weights,
    chip_bytes,
    gate,
    resource_need,
)
from earthlab.team.request_flow import ASK, ENDORSE, run_request
from earthlab.team.resources import ResourceDesk

GB = 10**9
GOOD = {
    "masks": ReferenceMasks(present=True, source="manual labels", derived_from=("field survey",)),
    "imagery": Imagery(
        bands=gates.HLS_BANDS, crs="EPSG:32649", resolution_m=30.0, coverage_fraction=0.95
    ),
    "weights": Weights(asset_id="prithvi", local_state="verified", permission="covered_signed"),
    "resources": Resources(
        free_disk_bytes=50 * GB, needed_bytes=2 * GB, ram_bytes=16 * GB, device="mps"
    ),
}


def request(**change: Any) -> SegmentationRequestV1:
    base = {"request_id": "seg-1", "question": "Map burn scars at 30 m.", "aoi": AOI} | GOOD
    return SegmentationRequestV1(**(base | change))


def codes(out: Any) -> list[str]:
    return [str(r.code) for r in out.refusals]


def test_a_complete_request_is_authorized() -> None:
    assert gate(request()).outcome == "authorized"


def test_mcd64a1_is_never_the_reference_mask() -> None:
    masks = ReferenceMasks(present=True, source="MCD64A1 burn date", derived_from=())
    out = gate(request(masks=masks))
    assert out.outcome == "request_resources" and "missing_labels" in codes(out)
    assert any("ground truth" in r.detail for r in out.refusals)
    derived = ReferenceMasks(present=True, source="threshold", derived_from=("mcd64a1",))
    assert "missing_labels" in codes(gate(request(masks=derived)))
    assert "missing_labels" in codes(gate(request(masks=ReferenceMasks(present=False))))


def test_the_six_bands_must_be_present_and_in_order() -> None:
    missing = Imagery(
        bands=("red", "nir_narrow"), crs="EPSG:32649", resolution_m=30.0, coverage_fraction=0.9
    )
    assert any("missing bands" in r.detail for r in gate(request(imagery=missing)).refusals)
    swapped = Imagery(
        bands=("green", "blue", *gates.HLS_BANDS[2:]),
        crs="EPSG:32649",
        resolution_m=30.0,
        coverage_fraction=0.9,
    )
    assert any("order" in r.detail for r in gate(request(imagery=swapped)).refusals)
    twice = Imagery(
        bands=(*gates.HLS_BANDS, "red"), crs="EPSG:32649", resolution_m=30.0, coverage_fraction=0.9
    )
    assert any("twice" in r.detail for r in gate(request(imagery=twice)).refusals)


def test_crs_resolution_and_coverage_are_required() -> None:
    bare = Imagery(bands=gates.HLS_BANDS, crs=None, resolution_m=500.0, coverage_fraction=None)
    out = gate(request(imagery=bare))
    text = " ".join(r.detail for r in out.refusals)
    assert "CRS" in text and "resolution 500.0" in text and "coverage None" in text
    assert out.needs[0].estimated_bytes == chip_bytes(2) == 6_291_456


def test_hyperspectral_claims_are_refused_with_no_route() -> None:
    hyper = Imagery(
        bands=(), crs="EPSG:32649", resolution_m=60.0, coverage_fraction=0.9, hyperspectral=True
    )
    out = gate(request(imagery=hyper))
    assert (
        out.outcome == "refused"
        and out.route == ()
        and any("multispectral" in r.detail for r in out.refusals)
    )


def test_unsigned_or_unverified_weights_and_small_machines_block() -> None:
    chat = Weights(asset_id="prithvi", local_state="verified", permission="chat_only_unsigned")
    out = gate(request(weights=chat))
    assert out.outcome == "request_resources" and "signed approval" in out.needs[0].item
    absent = Weights(asset_id="prithvi", local_state="absent", permission="covered_signed")
    assert "unsupported_method" in codes(gate(request(weights=absent)))
    small = Resources(free_disk_bytes=GB, needed_bytes=2 * GB, ram_bytes=4 * GB, device="cpu")
    assert codes(gate(request(resources=small))).count("over_budget") == 2


def test_the_route_reaches_a_human_and_no_score_exists(tmp_path: Path) -> None:
    out = gate(request(masks=ReferenceMasks(present=False)))
    assert out.route[-1] == "human" and "nothing was run" in out.notes[0]
    item = Need(item="six-band HLS window", estimated_bytes=chip_bytes(2))
    with pytest.raises(ValueError, match="availability query"):
        resource_need(item, None, "HLS L30 pilot")
    need = resource_need(item, "https://data.example.org/hls/pilot.tif", "HLS L30 pilot")
    asked = {"purpose": "Score the model.", "scientific_need": "Six-band pair.", "risk": "Low."}
    client = ScriptedClient(
        [
            call(ASK, **asked),
            call(ENDORSE, endorse=True, note="Needed."),
            call(ENDORSE, endorse=True, note="In scope."),
        ]
    )
    view = run_request(tmp_path, client, need, "seg-req-1", "lead.seg")
    assert view.status == "pm_endorsed" and view.approval_sha256 is None
    assert [v.request.request_id for v in ResourceDesk(tmp_path).all()] == ["seg-req-1"]
    assert view.request.max_bytes == chip_bytes(2) and len(client.requests) == 3
