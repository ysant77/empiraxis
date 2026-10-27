"""Tests for MCD64A1 burned area: a synthetic raster with a known answer, the verifier's
pre-registered checks, fail-closed reading, and the pinned Kalimantan 2015 case."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import tifffile
import yaml

from earthlab import cli
from earthlab.agent.findings import FindingsLedger
from earthlab.cases.loader import load_case
from earthlab.cases.models import BoundingBox
from earthlab.data.mcd64a1 import aligned, load_month
from earthlab.data.snapshot import SourceMismatchError
from earthlab.digest import file_digest
from earthlab.runtime import build_registry, open_workspace
from earthlab.science.burned_area import month_doy_range, summarize_month, wgs84_pixel_area
from earthlab.tools.burned_area_tools import METHOD_FILE, case_report
from earthlab.verify.burned_area_check import (
    MonthCheck,
    Tolerances,
    check_month,
    claim_verdict,
    load_tolerances,
)

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "config" / "cases" / "kalimantan-2015-burned-area.yaml"
SX = 463.3127165279165
PRODUCT = [SX, 0.0, -20015109.354, 0.0, -SX, 7783653.6376640005]
TOL = load_tolerances(ROOT / METHOD_FILE)


def write_month(
    folder: Path, burn: np.ndarray, qa: np.ndarray, *, x0: float, y0: float
) -> dict[str, Any]:
    """A 5-band int16 GeoTIFF on the product grid, plus its manifest entry."""
    stack = np.stack([burn, np.zeros_like(burn), qa, burn, burn]).astype(np.int16)
    matrix = [SX, 0, 0, x0, 0, -SX, 0, y0, 0, 0, 0, 0, 0, 0, 0, 1]
    path = folder / "m.tif"
    tifffile.imwrite(path, stack, extratags=[(34264, "d", 16, matrix, True)])
    return {
        "file": "m.tif",
        "month": "2015-09",
        "sha256": file_digest(path),
        "bytes": 1,
        "grid": {"crs": "SR-ORG:6974", "crs_transform": PRODUCT},
        "bands": ["BurnDate", "Uncertainty", "QA", "FirstDay", "LastDay"],
        "reference": {},
    }


def synthetic(tmp_path: Path) -> tuple[Path, dict[str, Any], BoundingBox]:
    """A 4x4 block just south of the equator; six cells of known classes."""
    x0, y0 = PRODUCT[2] + 43200 * SX, 0.0  # whole pixels from the product origin
    burn = np.full((4, 4), -1)
    qa = np.full((4, 4), 3)  # land and valid
    burn[0, 0] = burn[0, 1] = burn[1, 1] = 250  # burned in September (DOY 244-273)
    burn[2, 2] = 250
    qa[2, 2] = 1  # burned but no valid data: not counted
    burn[3, 3] = 300  # outside September
    qa[3, 0] = 0  # water
    entry = write_month(tmp_path, burn, qa, x0=x0, y0=y0)
    lon0 = np.degrees(x0 / 6371007.181)
    box = BoundingBox(min_lon=lon0, min_lat=-0.0167, max_lon=lon0 + 0.0167, max_lat=0.0)
    (tmp_path / "man.json").write_text(json.dumps({"files": [entry]}))
    return tmp_path, entry, box


def test_synthetic_raster_gives_the_known_answer(tmp_path: Path) -> None:
    folder, entry, box = synthetic(tmp_path)
    raster = load_month(folder, "man.json", "2015-09")
    summary = summarize_month(raster, box, 0.8)
    assert (
        summary.pixels_in_box == 16
        and summary.land_pixels == 15
        and summary.valid_land_pixels == 14
    )
    assert summary.burned_pixels == 3 and summary.burn_date_outside_month == 1
    expected = sum(wgs84_pixel_area(r, c, raster.grid) for r, c in [(0, 0), (0, 1), (1, 1)])
    assert summary.primary_area_m2 == pytest.approx(expected, abs=0.1)
    assert summary.nominal_area_m2 == pytest.approx(3 * SX * SX, abs=0.1)
    per_px = summary.primary_area_m2 / 3
    entry["reference"] = {"burned_valid_pixels": 3, "burned_valid_area_m2": per_px * 3}
    check = check_month(summary, folder, entry, box, month_doy_range("2015-09"), TOL)
    assert check.passed and check.verifier_burned_pixels == 3
    assert check.verifier_area_m2 == pytest.approx(
        summary.primary_area_m2, rel=TOL.tool_vs_verifier_relative_max
    )


def test_checks_fail_on_a_count_or_area_mismatch(tmp_path: Path) -> None:
    folder, entry, box = synthetic(tmp_path)
    summary = summarize_month(load_month(folder, "man.json", "2015-09"), box, 0.8)
    entry["reference"] = {
        "burned_valid_pixels": 3 + summary.burned_pixels_near_edge + 1,
        "burned_valid_area_m2": summary.primary_area_m2 * 1.01,
    }
    check = check_month(summary, folder, entry, box, month_doy_range("2015-09"), TOL)
    assert not check.c1_count_ok and not check.c2_per_pixel_area_ok and not check.passed
    tampered = summary.model_copy(update={"primary_area_m2": summary.primary_area_m2 * 1.01})
    entry["reference"]["burned_valid_pixels"] = 3
    assert not check_month(
        tampered, folder, entry, box, month_doy_range("2015-09"), TOL
    ).c3_tool_vs_verifier_ok


def test_reader_fails_closed(tmp_path: Path) -> None:
    folder = synthetic(tmp_path)[0]
    (folder / "m.tif").write_bytes((folder / "m.tif").read_bytes() + b"x")
    with pytest.raises(SourceMismatchError, match="sha256"):
        load_month(folder, "man.json", "2015-09")
    assert aligned(PRODUCT, PRODUCT)
    assert not aligned([SX, 0, PRODUCT[2] + SX / 2, 0, -SX, PRODUCT[5]], PRODUCT)
    assert not aligned([SX * 2, 0, PRODUCT[2], 0, -SX * 2, PRODUCT[5]], PRODUCT)
    with pytest.raises(SourceMismatchError, match="no single entry"):
        load_month(folder, "man.json", "2015-10")


def _check(**changes: Any) -> MonthCheck:
    base: dict[str, Any] = {
        "month": "2015-09",
        "verifier_burned_pixels": 10,
        "verifier_area_m2": 1e6,
        "verifier_valid_fraction": 0.9,
        "ee_burned_pixels": 10,
        "verifier_area_per_pixel_m2": 1e5,
        "ee_area_per_pixel_m2": 1e5,
        "allowed_count_difference": 0,
        "c1_count_ok": True,
        "c2_per_pixel_area_ok": True,
        "c3_tool_vs_verifier_ok": True,
        "gate_ok": True,
        "passed": True,
        "notes": [],
    }
    return MonthCheck.model_validate({**base, **changes})


def test_claim_verdicts() -> None:
    assert claim_verdict(100.0, _check(), TOL)[0] == "supported_observation"
    assert claim_verdict(100.05, _check(), TOL)[0] == "supported_observation"  # within 0.1%
    assert claim_verdict(120.0, _check(), TOL)[0] == "contradicted"
    low = _check(gate_ok=False, notes=["valid fraction 0.460 is below 0.8"])
    assert claim_verdict(100.0, low, TOL) == (
        "insufficient_data",
        "valid fraction 0.460 is below 0.8",
    )
    assert claim_verdict(100.0, _check(passed=False), TOL)[0] == "not_verified"


def test_pre_registered_values_are_the_committed_ones() -> None:
    raw = yaml.safe_load((ROOT / METHOD_FILE).read_text(encoding="utf-8"))
    assert raw["reporting_gate"]["min_valid_fraction"] == 0.8
    assert (
        Tolerances(
            min_valid_fraction=0.8,
            per_pixel_area_relative_max=0.0001,
            tool_vs_verifier_relative_max=0.0001,
            claim_relative_max=0.001,
        )
        == TOL
    )


def test_kalimantan_2015_passes_every_check_and_october_is_gated() -> None:
    september, october = case_report(load_case(CASE, ROOT), ROOT)
    for report in (september, october):
        s, c = report["summary"], report["check"]
        assert c["passed"] and c["verifier_burned_pixels"] == s["burned_pixels"]
        assert abs(s["burned_pixels"] - c["ee_burned_pixels"]) <= c["allowed_count_difference"]
        assert (
            abs(c["verifier_area_per_pixel_m2"] / c["ee_area_per_pixel_m2"] - 1)
            <= TOL.per_pixel_area_relative_max
        )
        assert s["primary_area_m2"] < s["nominal_area_m2"]  # ellipsoid pixel is smaller here
    assert september["summary"]["gate_passed"] and september["summary"]["valid_fraction"] > 0.95
    assert not october["summary"]["gate_passed"] and october["summary"]["valid_fraction"] < 0.5
    assert "below 0.8" in october["check"]["notes"][0]


def test_tool_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    registry = build_registry(open_workspace(ROOT / "data" / "nea"), FindingsLedger())
    ok = registry.execute(
        "burned_area_summary",
        json.dumps({"case_id": "kalimantan-2015-burned-area", "month": "2015-09"}),
    )
    assert ok.data is not None and ok.data["check"]["passed"]
    blocked = registry.execute(
        "burned_area_summary",
        json.dumps({"case_id": "uttarakhand-2024-burned-area", "month": "2024-04"}),
    )
    assert blocked.error is not None and "no pinned MCD64A1" in blocked.error
    out = tmp_path / "report.json"
    assert cli.main(["burned-area", "--case", str(CASE), "--output", str(out)]) == 0
    assert "insufficient_data" in capsys.readouterr().out and len(json.loads(out.read_text())) == 2
