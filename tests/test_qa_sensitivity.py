"""SB-07: MCD64A1 area under the pre-registered QA policies. The tool and the independent
verifier apply each policy separately; the gate and the tolerances do not change."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_burned_area import TOL, synthetic, write_month

from earthlab.agent.area_findings import AreaClaim, verify_area_claim
from earthlab.agent.findings import FindingsLedger
from earthlab.bench.scenarios import AreaRequirement, load_scenarios
from earthlab.cases.loader import load_case
from earthlab.cases.models import BoundingBox
from earthlab.data.mcd64a1 import load_month
from earthlab.runtime import Workspace, build_registry, open_workspace
from earthlab.science.burned_area import (
    QA_POLICY_FILE,
    QaPolicy,
    load_qa_policies,
    month_doy_range,
    summarize_month,
)
from earthlab.tools.burned_area_tools import month_report
from earthlab.verify.burned_area_check import check_month
from earthlab.verify.claims import Verdict

ROOT = Path(__file__).resolve().parents[1]
CASE = "kalimantan-2015-burned-area"
CASE_FILE = ROOT / "config" / "cases" / f"{CASE}.yaml"


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(ROOT / "data" / "nea")


def test_policies_are_the_pre_registered_ones() -> None:
    assert load_qa_policies(ROOT / QA_POLICY_FILE) == {
        QaPolicy.PRIMARY: (),
        QaPolicy.FULL_PERIOD: (2,),
        QaPolicy.NOT_RELABELED: (3,),
        QaPolicy.STRICT: (2, 3),
    }


def test_synthetic_policies_drop_only_flagged_burned_pixels(tmp_path: Path) -> None:
    folder, _, box = flagged(tmp_path)  # burned: (0,0) shortened, (0,1) relabeled, (1,1)
    raster = load_month(folder, "man.json", "2015-09")
    expected = {
        QaPolicy.PRIMARY: 3,
        QaPolicy.FULL_PERIOD: 2,
        QaPolicy.NOT_RELABELED: 2,
        QaPolicy.STRICT: 1,
    }
    for policy, bits in load_qa_policies(ROOT / QA_POLICY_FILE).items():
        summary = summarize_month(raster, box, 0.8, exclude_bits=bits)
        assert summary.burned_pixels == expected[policy]
        assert summary.valid_land_pixels == 14 and summary.gate_passed  # gate unchanged


def flagged(tmp_path: Path) -> tuple[Path, dict[str, Any], BoundingBox]:
    """The synthetic month with burned (0,0) shortened and burned (0,1) relabeled."""
    folder, _, box = synthetic(tmp_path)
    raster = load_month(folder, "man.json", "2015-09")
    burn, qa = raster.bands["BurnDate"].copy(), raster.bands["QA"].copy()
    qa[0, 0] |= 4
    qa[0, 1] |= 8
    entry = write_month(folder, burn, qa, x0=raster.grid.x0, y0=raster.grid.y0)
    (folder / "man.json").write_text(json.dumps({"files": [entry]}))
    return folder, entry, box


def test_verifier_applies_the_policy_on_its_own_read(tmp_path: Path) -> None:
    """The verifier re-reads the file; a summary for another policy fails C3."""
    folder, entry, box = flagged(tmp_path)
    days = month_doy_range("2015-09")
    raster = load_month(folder, "man.json", "2015-09")
    strict = summarize_month(raster, box, 0.8, exclude_bits=(2, 3))
    ok = check_month(strict, folder, entry, box, days, TOL, exclude_bits=(2, 3))
    assert ok.passed and ok.verifier_burned_pixels == 1
    assert ok.c1_count_ok is None and ok.c2_per_pixel_area_ok is None  # no EE reference
    entry["reference"] = {"burned_valid_pixels": 3, "burned_valid_area_m2": 1.0}
    wrong = check_month(strict, folder, entry, box, days, TOL)  # verifier applies primary
    assert not wrong.c3_tool_vs_verifier_ok and not wrong.passed


def test_kalimantan_september_policies_pass_and_october_stays_gated() -> None:
    case = load_case(CASE_FILE, ROOT)
    areas = {}
    for policy in QaPolicy:
        report = month_report(case, ROOT, "2015-09", policy)
        assert report["qa_policy"] == policy.value and report["check"]["passed"]
        assert report["check"]["c3_tool_vs_verifier_ok"]
        areas[policy] = report["summary"]["primary_area_ha"]
        october = month_report(case, ROOT, "2015-10", policy)
        assert not october["check"]["gate_ok"]
    assert areas[QaPolicy.STRICT] <= areas[QaPolicy.FULL_PERIOD] <= areas[QaPolicy.PRIMARY]
    assert areas[QaPolicy.STRICT] <= areas[QaPolicy.NOT_RELABELED] <= areas[QaPolicy.PRIMARY]
    primary = month_report(case, ROOT, "2015-09")
    assert primary["check"]["c1_count_ok"] and primary["check"]["c2_per_pixel_area_ok"]


def test_policy_claims_are_verified_against_their_own_policy(workspace: Workspace) -> None:
    library = workspace.cases
    assert library is not None
    strict = month_report(library.get(CASE), ROOT, "2015-09", QaPolicy.STRICT)
    value = strict["summary"]["primary_area_ha"]
    base = {
        "case_id": CASE,
        "month": "2015-09",
        "quantity": "burned_area_ha",
        "statement": "Mapped burned area under the strict QA policy.",
        "qa_policy": "strict",
    }
    good = verify_area_claim(AreaClaim.model_validate({**base, "value": value}), library)
    assert good.verdict is Verdict.SUPPORTED
    bad = verify_area_claim(AreaClaim.model_validate({**base, "value": value * 1.01}), library)
    assert bad.verdict is Verdict.CONTRADICTED
    gated = verify_area_claim(
        AreaClaim.model_validate({**base, "month": "2015-10", "value": 1.0}), library
    )
    assert gated.verdict is Verdict.INSUFFICIENT_DATA
    need = AreaRequirement(case_id=CASE, month="2015-09", qa_policy=QaPolicy.STRICT)
    assert need.met_by(good) and not AreaRequirement(case_id=CASE, month="2015-09").met_by(good)


def test_tool_takes_a_policy_and_rejects_an_unknown_one(workspace: Workspace) -> None:
    registry = build_registry(workspace, FindingsLedger())
    args = {"case_id": CASE, "month": "2015-09", "qa_policy": "strict"}
    ok = registry.execute("burned_area_summary", json.dumps(args))
    assert ok.data is not None and ok.data["qa_policy"] == "strict"
    bad = registry.execute("burned_area_summary", json.dumps({**args, "qa_policy": "lenient"}))
    assert bad.error is not None


def test_w2_scenarios_are_ready() -> None:
    scenarios = {s.id: s for s in load_scenarios(ROOT / "evals" / "sciencebench_dev_v1.yaml")}
    sb07 = scenarios["SB-07"]
    assert sb07.status == "ready" and sb07.expected == "verified_claims"
    assert {r.qa_policy for r in sb07.area_requirements} == set(QaPolicy)
    assert scenarios["SB-05c"].reason_codes == ["insufficient_valid_data"]
    assert scenarios["SB-05d"].reason_codes == ["causation_not_identifiable"]
