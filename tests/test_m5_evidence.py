from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from earthlab.m5.evidence import EvidencePackage, build, verify

ROOT = Path(__file__).resolve().parents[1]


def test_package_hash_verifies_and_is_frozen() -> None:
    pkg = build(ROOT)
    assert verify(pkg)
    with pytest.raises(ValidationError):
        pkg.version = "x"  # type: ignore[misc]


def test_tampering_breaks_the_hash() -> None:
    pkg = build(ROOT)
    forged = pkg.model_copy(update={"limitations": []})
    assert not verify(forged)


def test_issue_time_and_retrospective_inputs_are_separate() -> None:
    pkg = build(ROOT)
    by_source = {r.source: r.input_class for r in pkg.source_rules}
    assert by_source["era5"] == "retrospective_only"
    assert by_source["imerg_early"] == "issue_time_valid"
    assert {f.input_class for f in pkg.features if f.source == "era5"} == {"retrospective_only"}


def test_committed_package_matches_artifacts() -> None:
    path = ROOT / "docs/m5/evidence/scientific_evidence_package_v1.json"
    committed = EvidencePackage.model_validate(json.loads(path.read_text()))
    assert verify(committed)
    assert committed == build(ROOT)


def test_questions_are_registered_verbatim() -> None:
    pkg = build(ROOT)
    assert set(pkg.questions) == {"M5-A", "M5-B", "M5-C"}
    assert pkg.primary_question == "M5-A"
