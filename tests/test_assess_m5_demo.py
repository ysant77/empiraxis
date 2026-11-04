"""The demonstration package from the merged M5 evidence: hash checks, M5-C facts, frozen IDs."""

from __future__ import annotations

import hashlib
import json

import pytest
from assess_fakes import ROOT
from test_assess_m5_adapter import PATH, STAGE_T, _m5

from earthlab.assess import policy
from earthlab.assess.contracts import EvidencePackageV1
from earthlab.assess.m5_adapter import PACKAGE_ID, ArtifactMismatch
from earthlab.assess.m5_demo import DEMO_ID, M5C_PATH, build

RUNG = {"brier_skill": 0.47, "skill_ci": [0.27, 0.64]}
M5C = json.dumps(
    {
        "data": {
            "main": {"episodes": 1, "events": 349, "C2": RUNG, "C3": {**RUNG, "label": "u"}},
            "sensitivity_firms_delay_24h": {"C2": RUNG, "C3": RUNG},
            "diagnostic_season_rank_hindsight": {"C2": RUNG, "C3": RUNG},
        }
    }
).encode()
FILES = {PATH: STAGE_T, M5C_PATH: M5C}


def _demo_m5(m5c_digest: str) -> dict[str, object]:
    m5 = _m5(hashlib.sha256(STAGE_T).hexdigest())
    m5["artifacts"] = [*m5["artifacts"], {"path": M5C_PATH, "sha256": m5c_digest}]
    return m5


def test_demo_package_adds_m5c_facts_and_limits() -> None:
    pkg = build(_demo_m5(hashlib.sha256(M5C).hexdigest()), FILES.__getitem__, "35de956ff")
    assert pkg.package_id == DEMO_ID != PACKAGE_ID
    facts = {f.id: f for f in pkg.facts}
    assert facts["c19.episodes"].value == 1 and facts["c19.C3.skill_low"].value == 0.27
    assert "frozen label u" in facts["c19.C3.skill"].statement
    assert {"c19d24.C3.skill", "c19rank.C3.skill"} <= set(facts)
    m5c = next(s for s in pkg.sources if s.id == "m5_c")
    assert m5c.origin.startswith("m5@35de956:") and m5c.sha256 == hashlib.sha256(M5C).hexdigest()
    text = " ".join(pkg.limitations)
    for words in ("no answer key", "computed none", "not the near-real-time", "ERA5", "reused"):
        assert words in text
    cited = {e for f in policy.decide(pkg).flags for e in f.evidence}
    assert cited <= set(facts) | {s.id for s in pkg.sources}


def test_demo_package_refuses_a_changed_m5c_file() -> None:
    with pytest.raises(ArtifactMismatch):
        build(_demo_m5("d" * 64), FILES.__getitem__, "35de956ff")


def test_frozen_benchmark_package_is_separate() -> None:
    folder = ROOT / "examples" / "assess" / "packages"
    demo = EvidencePackageV1.model_validate_json((folder / f"{DEMO_ID}.json").read_text())
    frozen = EvidencePackageV1.model_validate_json((folder / f"{PACKAGE_ID}.json").read_text())
    assert frozen.package_id == PACKAGE_ID
    assert all("m5@458f297" in s.origin for s in frozen.sources if s.id.startswith("m5_"))
    assert all("m5@35de956" in s.origin for s in demo.sources if s.id.startswith("m5_"))
