from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from earthlab.assess import policy
from earthlab.assess.contracts import Availability
from earthlab.assess.m5_adapter import ArtifactMismatch, adapt, availability

STAGE_T = json.dumps(
    {
        "2019": {
            "mae": {"R0": 11.3, "R1": 9.9, "R2": 11.2},
            "elevated_mae": {"R0": 27.6, "R1": 28.2, "R2": 17.3},
            "paired": {"R2_vs_R1": {"skill": -0.135, "low": -0.255, "high": -0.039}},
            "elevated_days": 17,
        }
    }
).encode()
PATH = "docs/m5/results/m5_ladder_stage_t.json"


def _m5(digest: str) -> dict[str, Any]:
    rules = [
        ("nea_pm25", "issue_time_valid", 2.0),
        ("imerg_final", "issue_time_valid", 2556.0),
        ("imerg_late", "issue_time_valid", 14.0),
        ("smap_l3", "issue_time_valid", 50.0),
        ("era5", "retrospective_only", None),
        ("firms_modis_sp", "issue_time_valid", 3.0),
    ]
    return {
        "version": "m5-evidence-1",
        "questions": {"M5-A": "Can wind help?"},
        "primary_question": "M5-A",
        "period": "2015",
        "package_sha256": "b" * 64,
        "source_rules": [{"source": s, "input_class": c, "latency_hours": h} for s, c, h in rules],
        "modalities": [
            {"source": "nea_pm25", "status": "used", "reason": "target"},
            {"source": "imerg_late", "status": "not_assessed", "reason": "no data"},
            {"source": "firms_modis_sp", "status": "used", "reason": "fire counts"},
        ],
        "features": [
            {"source": "nea_pm25", "input_class": "issue_time_valid"},
            {"source": "firms_modis_sp", "input_class": "issue_time_valid"},
        ],
        "artifacts": [{"path": PATH, "sha256": digest}],
        "baselines": {
            "stage_p_2015_mae": {"R0": 30.76},
            "stage_p_2016_mae": {"R0": 8.6},
            "stage_p_2015_i1_mae": {"I1": 36.1},
        },
        "limitations": ["Five regions."],
        "claims_not_made": ["No cause."],
    }


def test_adapter_reads_the_package_and_checks_hashes() -> None:
    m5 = _m5(hashlib.sha256(STAGE_T).hexdigest())
    pkg = adapt(m5, lambda rel: STAGE_T, "feeeef9aaaa")
    avail = {s.id: s.availability for s in pkg.sources}
    assert avail["nea_pm25"] is Availability.ISSUE_TIME_VALID
    assert avail["imerg_final"] is Availability.HINDSIGHT
    assert avail["imerg_late"] is Availability.UNKNOWN and avail["era5"] is Availability.HINDSIGHT
    # a timely product whose archive is not the issue-time product is not a valid input
    assert avail["firms_modis_sp"] is Availability.UNKNOWN
    nea = next(s for s in pkg.sources if s.id == "nea_pm25")
    assert nea.input_cutoff_hours == 2.0
    assert nea.availability_basis == "nominal_latency_with_enforced_cutoff"
    assert {f.id for f in pkg.facts} >= {"p15.R0", "t19.R2_vs_R1.skill", "t19.elev_days"}
    rule = policy.decide(pkg)
    assert "era5" in rule.excluded_inputs and rule.eligible_inputs == ["nea_pm25"]
    assert {"firms_modis_sp", "imerg_late"} <= set(rule.excluded_inputs)
    cited = {e for f in rule.flags for e in f.evidence}
    assert cited <= {f.id for f in pkg.facts} | {s.id for s in pkg.sources}
    assert pkg.missing_inputs == ["imerg_late: no data"]


def test_adapter_refuses_a_changed_artifact() -> None:
    with pytest.raises(ArtifactMismatch):
        adapt(_m5("c" * 64), lambda rel: STAGE_T, "feeeef9")


@pytest.mark.parametrize(
    ("source", "latency", "status", "cutoff", "want"),
    [
        ("imerg_early", 4.0, "used", True, Availability.ISSUE_TIME_VALID),
        ("imerg_early", 4.0, "used", False, Availability.UNKNOWN),  # no enforced cutoff
        ("imerg_early", 4.0, "gated_out", True, Availability.UNKNOWN),
        ("firms_modis_sp", 3.0, "used", True, Availability.UNKNOWN),  # archive is not NRT
        ("imerg_early", None, "used", True, Availability.HINDSIGHT),
        ("smap_l3", 50.0, "used", True, Availability.HINDSIGHT),
    ],
)
def test_availability_rule(
    source: str, latency: float | None, status: str, cutoff: bool, want: Availability
) -> None:
    rule = {"source": source, "input_class": "issue_time_valid", "latency_hours": latency}
    assert availability(rule, status, cutoff)[0] is want
