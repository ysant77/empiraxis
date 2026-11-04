from __future__ import annotations

import hashlib
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


V4_FILE_SHA256 = "b0ad01a1b7b4b0346edc5841b541747b34c773f62dfebbf8128357ab3dbe3497"


def test_committed_m5_evidence_4_is_frozen() -> None:
    """The v4 file stays byte-identical. Its artifact digests describe the files at its commit.

    The report gained a dated correction note later, so a fresh build() no longer equals the file.
    The current package is m5-evidence-5 (tests/test_m5_evidence_v2.py).
    """
    path = ROOT / "docs/m5/evidence/scientific_evidence_package_v1.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == V4_FILE_SHA256
    committed = EvidencePackage.model_validate(json.loads(path.read_text()))
    assert verify(committed)
    assert committed.version == "m5-evidence-4"


def test_questions_are_registered_verbatim() -> None:
    pkg = build(ROOT)
    assert set(pkg.questions) == {"M5-A", "M5-B", "M5-C"}
    assert pkg.primary_question == "M5-A"
