"""Acceptance tests for the typed case contracts (areas, periods, assets, methods, claims,
approvals) and the feasibility check. IDs match the approved test plan."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from pydantic import BaseModel, ValidationError

from earthlab.agent.findings import FindingsLedger
from earthlab.cases.loader import asset_from_manifest, claim_from_verification, load_case
from earthlab.cases.methods import CATALOGUE, assess, claim_problems, get_method
from earthlab.cases.models import (
    ApprovalAction,
    BoundingBox,
    CausalStatus,
    EvidenceClaim,
    HumanApproval,
    ObservationStatus,
    ScientificCase,
    SourceAsset,
    StudyArea,
    StudyPeriod,
)
from earthlab.contracts import TimeWindow
from earthlab.runtime import build_registry, open_workspace
from earthlab.verify.claims import Claim

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "config" / "cases"
BOX = {"min_lon": 113.8, "min_lat": -3.2, "max_lon": 114.8, "max_lat": -2.0}
SHA = "a" * 64
UTC_PERIOD = {"start": "2015-09-01T00:00:00Z", "end": "2015-11-01T00:00:00Z", "local_zone": "UTC"}
NOW = datetime.fromisoformat("2026-10-28T00:00:00+00:00")


def area(**box: float) -> StudyArea:
    return StudyArea(area_id="aoi", name="AOI", bbox=BoundingBox(**{**BOX, **box}))


def asset(**changes: Any) -> SourceAsset:
    base: dict[str, Any] = {
        "asset_id": "mcd64a1",
        "product": "MODIS/061/MCD64A1",
        "version": "6.1",
        "provider": "NASA",
        "variable": "burned_area",
        "units": "BurnDate",
        "licence": "open",
        "licence_url": "https://example.org/l",
        "url": "https://example.org/d",
        "availability": "pinned",
        "sha256": SHA,
        "bytes": 10,
        "retrieved_at_utc": "2026-10-28T00:00:00Z",
        "crs": "SR-ORG:6974",
        "coverage": UTC_PERIOD,
        "extent": BOX,
        "quality_policy": "QA bits",
    }
    return SourceAsset.model_validate({**base, **changes})


def case(**changes: Any) -> ScientificCase:
    base: dict[str, Any] = {
        "case_id": "kal",
        "title": "Kalimantan",
        "question": "How much area burned?",
        "area": area(),
        "period": UTC_PERIOD,
        "variable": "burned_area",
        "asset_ids": ["mcd64a1"],
        "method_id": "mcd64a1_burned_area",
    }
    return ScientificCase.model_validate({**base, **changes})


BURN = CATALOGUE["mcd64a1_burned_area"]
BURN_READY = BURN.model_copy(update={"implemented": True})


# A1-A8: study areas
@pytest.mark.parametrize(
    ("box", "message"),
    [
        ({"min_lon": 181.0}, "less than or equal to 180"),  # A2
        ({"max_lat": -95.0}, "greater than or equal to -90"),  # A2
        ({"min_lat": -1.0}, "min_lat must be below max_lat"),  # A3
        ({"min_lon": 179.0, "max_lon": -179.0}, "antimeridian"),  # A4
        ({"max_lon": 120.0}, "wider than 5.0 degrees"),  # A5
    ],
)
def test_bad_areas_are_rejected(box: dict[str, float], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        area(**box)


def test_area_geometry_rules() -> None:
    assert area().bbox is not None  # A1
    with pytest.raises(ValidationError, match="exactly one"):  # A6
        StudyArea(area_id="x", name="x", bbox=BoundingBox(**BOX), regions=("west",))
    with pytest.raises(ValidationError, match="exactly one"):
        StudyArea(area_id="x", name="x")
    with pytest.raises(ValidationError, match="needs its sha256"):  # A7
        StudyArea(area_id="x", name="x", bbox=BoundingBox(**BOX), geojson_ref="a.geojson")
    with pytest.raises(ValidationError):
        StudyArea.model_validate({"area_id": "x", "name": "x", "bbox": BOX, "crs": "EPSG:3857"})
    assert StudyArea(area_id="nea", name="NEA", regions=("west", "east")).regions  # A8


# P1-P5: study periods
def test_period_rules() -> None:
    with pytest.raises(ValidationError, match="missing time zone"):  # P1
        StudyPeriod(start=datetime(2015, 9, 1), end=datetime(2015, 10, 1), local_zone="UTC")
    with pytest.raises(ValidationError, match="after period start"):  # P2
        StudyPeriod.model_validate({**UTC_PERIOD, "end": UTC_PERIOD["start"]})
    with pytest.raises(ValidationError, match="unknown time zone"):  # P3
        StudyPeriod.model_validate({**UTC_PERIOD, "local_zone": "Mars/Olympus"})


def test_period_converts_to_the_nea_window() -> None:  # P4
    period = StudyPeriod.model_validate(
        {
            "start": "2015-09-01T00:00+08:00",
            "end": "2015-09-02T00:00+08:00",
            "local_zone": "Asia/Singapore",
        }
    )
    expected = TimeWindow(start=datetime(2015, 9, 1), end=datetime(2015, 9, 2))
    assert period.to_window().hours() == expected.hours() and len(expected.hours()) == 24


def test_india_local_labels_and_half_open_bounds() -> None:  # P5
    period = StudyPeriod.model_validate(
        {"start": "2024-04-01T00:00Z", "end": "2024-06-01T00:00Z", "local_zone": "Asia/Kolkata"}
    )
    assert period.local_label().startswith("2024-04-01T05:30:00+05:30 to 2024-06-01T05:30")
    inner = StudyPeriod.model_validate(
        {**UTC_PERIOD, "start": "2024-05-01T00:00Z", "end": "2024-06-01T00:00Z"}
    )
    later = StudyPeriod.model_validate(
        {**UTC_PERIOD, "start": "2024-05-01T00:00Z", "end": "2024-06-01T01:00Z"}
    )
    assert period.contains(inner) and not period.contains(later)


# S1-S4: source assets
def test_asset_pin_rules() -> None:
    with pytest.raises(ValidationError, match="needs sha256, bytes"):  # S1
        asset(sha256=None)
    with pytest.raises(ValidationError, match="only a pinned asset"):  # S2
        asset(availability="registered_not_downloaded")
    with pytest.raises(ValidationError):  # S4
        asset(units="")


def test_nea_asset_keeps_the_manifest_hash() -> None:  # S3
    nea = asset_from_manifest(REPO_DATA / "manifest.json")
    snapshot = open_workspace(REPO_DATA).snapshot
    assert nea.sha256 == snapshot.sha256 and nea.bytes == snapshot.bytes
    assert nea.availability == "pinned" and len(nea.regions) == 5


# F1-F9: feasibility
def test_feasible_needs_approval_and_not_implemented() -> None:
    pinned = {"mcd64a1": asset()}
    assert assess(case(), BURN_READY, pinned).status == "feasible"  # F1
    registered = {
        "mcd64a1": asset(
            availability="registered_not_downloaded", sha256=None, bytes=None, retrieved_at_utc=None
        )
    }
    result = assess(case(), BURN_READY, registered)  # F2
    assert result.status == "needs_approval"
    assert result.approvals_needed == ((ApprovalAction.DOWNLOAD, "mcd64a1"),)
    assert assess(case(), BURN, pinned).status == "not_implemented"  # F7


def test_coverage_and_variable_mismatches_block() -> None:
    later = {**UTC_PERIOD, "start": "2015-10-01T00:00:00Z"}
    blocked = assess(case(), BURN_READY, {"mcd64a1": asset(coverage=later)})  # F3
    assert blocked.status == "blocked" and "temporal coverage" in blocked.reasons[0]
    elsewhere = {**BOX, "min_lon": 114.0}
    assert (
        "spatial coverage"
        in assess(case(), BURN_READY, {"mcd64a1": asset(extent=elsewhere)}).reasons[0]
    )  # F4
    firms = asset(
        asset_id="firms", product="FIRMS/MODIS_SP", variable="active_fire", crs="EPSG:4326"
    )
    only_firms = assess(case(asset_ids=["firms"]), BURN_READY, {"firms": firms})  # F5
    assert only_firms.status == "blocked"
    assert "active-fire detections are not burned area" in only_firms.reasons[0]
    lst = asset(asset_id="lst", product="MODIS/061/MOD11A1", variable="land_surface_temperature")
    heat = case(variable="air_temperature_anomaly", asset_ids=["lst"], method_id="era5_t2m_anomaly")
    mismatch = assess(heat, get_method("era5_t2m_anomaly"), {"lst": lst})  # F6
    assert "variable mismatch" in mismatch.reasons[0]
    assert "land-surface temperature is not 2 m air temperature" in mismatch.reasons[0]


def test_unknown_method_is_an_error() -> None:  # F9
    with pytest.raises(ValueError, match="unknown method"):
        get_method("magic_attribution")


def test_case_files_give_their_expected_results() -> None:  # R1, F8
    results = {}
    for path in sorted(CASES.glob("*.yaml")):
        loaded = load_case(path, ROOT)
        results[loaded.case.case_id] = assess(
            loaded.case, get_method(loaded.case.method_id), loaded.assets
        )
    assert results["nea-2015-haze"].status == "feasible"
    assert results["kalimantan-2015-burned-area"].status == "needs_approval"
    assert "not implemented yet" in results["kalimantan-2015-burned-area"].reasons[-1]
    india = results["uttarakhand-2024-burned-area"]
    assert india.status == "blocked" and "unavailable" in india.reasons[0]
    kal = load_case(CASES / "kalimantan-2015-burned-area.yaml", ROOT).case
    ind = load_case(CASES / "uttarakhand-2024-burned-area.yaml", ROOT).case
    assert kal.method_id == ind.method_id and kal.variable is ind.variable  # same code path


def test_case_file_shape_is_strict(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("case: {}\nassets: []\nextra: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly 'case' and 'assets'"):
        load_case(bad, ROOT)


# E1-E6: evidence claims
def evidence(**changes: Any) -> EvidenceClaim:
    base: dict[str, Any] = {
        "claim_id": "c1",
        "case_id": "kal",
        "method_id": "mcd64a1_burned_area",
        "variable": "burned_area",
        "area": area(),
        "period": UTC_PERIOD,
        "value": 1200.0,
        "unit": "ha",
        "source_sha256": [SHA],
        "valid_fraction": 0.95,
        "observation_status": "supported_observation",
    }
    return EvidenceClaim.model_validate({**base, **changes})


def test_claim_rules() -> None:
    with pytest.raises(ValidationError):  # E1
        evidence(causal_status="established")
    causal = case(causal_claim_requested=True)
    assert causal.default_causal_status() is CausalStatus.NOT_ESTABLISHED  # E2
    assert "causal status must be stated" in claim_problems(evidence(), causal, BURN)[0]
    with pytest.raises(ValidationError, match="needs value, source_sha256"):  # E3
        evidence(source_sha256=[])
    assert (
        "below the method minimum" in claim_problems(evidence(valid_fraction=0.5), case(), BURN)[0]
    )
    outside = evidence(area=area(min_lon=110.0, max_lon=114.0))  # E4
    assert claim_problems(outside, case(), BURN) == ["claim area lies outside the case area"]
    late = evidence(period={**UTC_PERIOD, "end": "2015-12-01T00:00:00Z"})
    assert claim_problems(late, case(), BURN) == ["claim period lies outside the case period"]
    assert "differs from method unit" in claim_problems(evidence(unit="km2"), case(), BURN)[0]  # E5
    assert claim_problems(evidence(), case(), BURN) == []


def test_nea_verdict_becomes_an_evidence_claim() -> None:  # E6
    workspace = open_workspace(REPO_DATA)
    nea = load_case(CASES / "nea-2015-haze.yaml", ROOT).case
    raw = {
        "kind": "region_max",
        "region": "west",
        "value": 471,
        "statement": "Seen.",
        "start": "2015-09-01T00:00",
        "end": "2015-11-01T00:00",
    }
    verdict = workspace.verifier.verify(Claim.model_validate(raw))
    source = workspace.verifier._source
    claim = claim_from_verification(verdict, "R1.1", nea, source, workspace.snapshot.sha256)
    assert claim.observation_status is ObservationStatus.SUPPORTED_OBSERVATION
    assert claim.source_sha256 == (workspace.snapshot.sha256,) and claim.valid_fraction == 1.0
    assert claim_problems(claim, nea, get_method("nea_hourly_episode")) == []


# H1-H3: human approvals
def approval(**changes: Any) -> HumanApproval:
    base: dict[str, Any] = {
        "approval_id": "a1",
        "case_id": "kal",
        "action": "download",
        "approved": True,
        "approver": "owner",
        "decided_at_utc": "2026-10-27T00:00:00Z",
        "expires_at_utc": "2026-10-29T00:00:00Z",
        "asset_ids": ["mcd64a1"],
        "max_bytes": 50_000_000,
    }
    return HumanApproval.model_validate({**base, **changes})


def test_approval_refusals() -> None:  # H1
    assert approval().refusal(ApprovalAction.DOWNLOAD, NOW, "mcd64a1") is None
    assert (
        approval(approved=False).refusal(ApprovalAction.DOWNLOAD, NOW)
        == "the approval was rejected"
    )
    late = datetime.fromisoformat("2026-11-01T00:00:00+00:00")
    assert "not valid at this time" in (approval().refusal(ApprovalAction.DOWNLOAD, late) or "")
    assert "not in the approval" in (approval().refusal(ApprovalAction.DOWNLOAD, NOW, "x") or "")
    assert "not publish" in (approval().refusal(ApprovalAction.PUBLISH, NOW) or "")


def test_approval_scope_rules() -> None:  # H2
    with pytest.raises(ValidationError, match="needs max_usd"):
        approval(action="hosted_model_spend", asset_ids=[], max_bytes=None)
    with pytest.raises(ValidationError, match="needs asset_ids and max_bytes"):
        approval(asset_ids=[])
    with pytest.raises(ValidationError, match="expire after"):
        approval(expires_at_utc="2026-10-26T00:00:00Z")


def test_no_tool_can_create_an_approval() -> None:  # H3
    registry = build_registry(open_workspace(REPO_DATA), FindingsLedger())
    text = str(registry.schemas()).lower()
    assert "approval" not in text and "approver" not in text


# R2: every record is strict and frozen
@pytest.mark.parametrize(
    "record",
    [area(), StudyPeriod.model_validate(UTC_PERIOD), asset(), evidence(), approval(), case(), BURN],
)
def test_records_reject_extra_fields_and_are_frozen(record: BaseModel) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        type(record).model_validate({**record.model_dump(), "injected": 1})
    with pytest.raises(ValidationError, match="frozen"):
        record.__setattr__(next(iter(type(record).model_fields)), None)


def test_remaining_fail_closed_paths() -> None:
    wrong_crs = assess(case(), BURN_READY, {"mcd64a1": asset(crs="EPSG:4326")})
    assert "CRS EPSG:4326" in wrong_crs.reasons[0]
    no_qa = assess(case(), BURN_READY, {"mcd64a1": asset(quality_policy=None)})
    assert "quality-flag policy" in no_qa.reasons[0]
    nea = get_method("nea_hourly_episode")
    assert "method measures" in assess(case(), nea, {"mcd64a1": asset()}).reasons[0]
    long_case = case(period={**UTC_PERIOD, "end": "2016-01-01T00:00:00Z"})
    long_cover = {**UTC_PERIOD, "end": "2016-02-01T00:00:00Z"}
    assert (
        "longer than 92 days"
        in assess(long_case, BURN_READY, {"mcd64a1": asset(coverage=long_cover)}).reasons[0]
    )
    assert "not registered" in assess(case(), BURN_READY, {}).reasons[0]
    other = evidence(case_id="other", variable="active_fire")
    assert claim_problems(other, case(), BURN)[:2] == [
        "claim names a different case or method",
        "claim variable differs from the case variable",
    ]
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        evidence(source_sha256=["XYZ"])


def test_peak_region_verdict_reads_its_value() -> None:
    workspace = open_workspace(REPO_DATA)
    nea = load_case(CASES / "nea-2015-haze.yaml", ROOT).case
    raw = {
        "kind": "peak_region",
        "region": "west",
        "statement": "Seen.",
        "start": "2015-09-01T00:00",
        "end": "2015-11-01T00:00",
    }
    verdict = workspace.verifier.verify(Claim.model_validate(raw))
    source = workspace.verifier._source
    claim = claim_from_verification(verdict, "R1.1", nea, source, workspace.snapshot.sha256)
    assert claim.value == 471.0 and claim.valid_fraction == 1.0
