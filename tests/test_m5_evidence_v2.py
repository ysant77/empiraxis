from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from earthlab.m5 import evidence as V4
from earthlab.m5 import evidence_v2 as V2

ROOT = Path(__file__).resolve().parents[1]
V2_FILE = ROOT / "docs/m5/evidence/scientific_evidence_package_v2.json"
V4_FILE = ROOT / "docs/m5/evidence/scientific_evidence_package_v1.json"
FOUR = {"verified_issue_time", "nominal_latency_assumed", "retrospective_only", "unknown"}


def test_there_are_exactly_four_classes_and_each_has_a_meaning() -> None:
    assert set(get_args(V2.AvailabilityClass)) == FOUR
    assert set(V2.CLASS_MEANING) == FOUR
    assert set(V2.build(ROOT).class_meaning) == FOUR


def test_package_verifies_is_frozen_and_the_committed_file_equals_a_fresh_build() -> None:
    pkg = V2.build(ROOT)
    assert V2.verify(pkg) and pkg.version == "m5-evidence-5" and pkg.supersedes == "m5-evidence-4"
    committed = V2.EvidencePackageV2.model_validate(json.loads(V2_FILE.read_text()))
    assert committed == pkg
    with pytest.raises(ValidationError):
        pkg.version = "x"  # type: ignore[misc]
    assert not V2.verify(pkg.model_copy(update={"limitations": []}))


def test_firms_and_imerg_early_are_nominal_latency_assumed_and_never_verified() -> None:
    pkg = V2.build(ROOT)
    by_source = {r.source: r.availability_class for r in pkg.source_rules}
    assert by_source["firms_modis_sp"] == "nominal_latency_assumed"
    assert by_source["imerg_early"] == "nominal_latency_assumed"
    assert by_source["nea_pm25"] == "nominal_latency_assumed"
    assert by_source["era5"] == "retrospective_only"
    assert by_source["mcd64a1"] == "retrospective_only"
    assert by_source["firms_nrt"] == "unknown"
    assert "verified_issue_time" not in set(by_source.values())
    assert "verified_issue_time" not in {f.availability_class for f in pkg.features}


def test_every_feature_takes_the_class_of_its_source() -> None:
    pkg = V2.build(ROOT)
    by_source = {r.source: r.availability_class for r in pkg.source_rules}
    assert pkg.features
    assert all(f.availability_class == by_source[f.source] for f in pkg.features)
    names = {f.name: f.availability_class for f in pkg.features}
    assert names["fire_count_box_{a,b,c}"] == "nominal_latency_assumed"
    assert names["rain_{6,24}h_box_{a,b,c}"] == "nominal_latency_assumed"
    assert names["era5_wind_rain_blh"] == "retrospective_only"


def test_the_old_two_class_field_is_gone_from_the_new_package() -> None:
    raw = json.loads(V2_FILE.read_text())
    assert all("input_class" not in r for r in raw["source_rules"] + raw["features"])
    reasons = {m["source"]: m["reason"] for m in raw["modalities"]}
    assert "issue-time with" not in reasons["firms_modis_sp"]
    assert "not verified" in reasons["firms_modis_sp"]


def test_v4_stays_the_same_and_v2_keeps_its_protocol_snapshots_and_numbers() -> None:
    v4 = json.loads(V4_FILE.read_text())
    v2 = json.loads(V2_FILE.read_text())
    assert v4["version"] == "m5-evidence-4"
    for key in ("protocol_sha256", "protocol_bc_sha256", "baselines", "assets", "questions"):
        assert v2[key] == v4[key], key
    assert v4["source_rules"][1]["input_class"] == "issue_time_valid"  # history is not rewritten


def test_the_report_headings_are_kept_and_get_dated_correction_notes() -> None:
    text = (ROOT / "docs/m5/M5_SCIENCE_REPORT.md").read_text()
    assert "## 2. Experiment B: issue-time-valid T+6 prediction\n" in text
    assert "## 9. Evidence package for M4 (ScientificEvidencePackageV1)\n" in text
    assert text.count("**Correction note (2026-11-04).**") == 2
    assert "m5-evidence-5" in text


def test_the_v4_builder_is_not_the_current_builder() -> None:
    assert V4.PACKAGE_VERSION == "m5-evidence-4" and V2.PACKAGE_VERSION == "m5-evidence-5"
