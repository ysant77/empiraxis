from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from assess_fakes import ROOT, finding, package

from earthlab.assess import checks, policy
from earthlab.assess.contracts import Availability, CritiqueV1, Decision, FindingV1
from earthlab.assess.critic_bench import (
    load_cases,
    load_seeded,
    rule_critique,
    run_bench,
    score,
    summary,
)
from earthlab.assess.score import load_keys


def test_policy_on_the_frozen_packages() -> None:
    got = {p: policy.decide(package(p)) for p in "abcd"}
    assert got["a"].preferred is Decision.REQUEST_VALIDATION
    assert got["b"].preferred is Decision.PROCEED_WITH_LIMITS
    assert got["c"].preferred is Decision.ABSTAIN
    assert got["d"].excluded_inputs == ["era5", "hls", "imerg_final", "smap"]
    assert {f.fault_class.value for f in got["c"].flags} == {
        "hindsight_as_forecast",
        "insufficient_evidence",
    }


def test_policy_keys_agree_with_the_code_rule() -> None:
    keys = load_keys(ROOT / "config" / "assess" / "answer-keys.yaml")
    for p in "abcd":
        pkg = package(p)
        assert policy.decide(pkg).preferred.value in keys[pkg.package_id].acceptable


def test_policy_needs_its_facts() -> None:
    pkg = package("a")
    broken = pkg.model_copy(update={"facts": [f for f in pkg.facts if f.id != "b4.mae"]})
    with pytest.raises(KeyError, match=r"b4\.mae"):
        policy.decide(broken)


def test_backed_finding_passes() -> None:
    f = FindingV1.model_validate(
        finding(
            "m1",
            "subgroup_deterioration",
            ["b4.mae_gt55"],
            cited={"b4.mae_gt55": 30.254},
            claim="B4 MAE above 55 is 30.254, worse than persistence.",
        )
    )
    assert checks.finding_problems(f, package("a")) == []


@pytest.mark.parametrize(
    ("kw", "problem"),
    [
        ({"evidence": ["nope"]}, "unknown ref nope"),
        ({"cited": {"b4.mae": 4.2}}, "cited b4.mae=4.2"),
        ({"cited": {"m3_eval": 1.0}}, "not a numeric fact"),
        ({"claim": "The ridge error is 3.217 here."}, "number 3.217"),
        ({"claim": "Haze is caused by the Kalimantan fires."}, "forbidden causal"),
    ],
)
def test_forged_findings_fail(kw: dict[str, Any], problem: str) -> None:
    evidence = kw.pop("evidence", ["b4.mae"])
    f = FindingV1.model_validate(finding("c1", "numeric_misstatement", evidence, **kw))
    assert any(problem in p for p in checks.finding_problems(f, package("a")))


def test_plan_report_blocks_hindsight_inputs_only_when_forecasting() -> None:
    d = package("d")
    report = checks.plan_report(
        "x",
        d,
        decision=Decision.PROCEED_WITH_LIMITS,
        inputs_used=["nea_pm25", "era5"],
        excluded=[],
        texts=["ok"],
    )
    assert {c.name: c.passed for c in report.checks}["issue_time_inputs"] is False
    b = package("b")
    report = checks.plan_report(
        "x",
        b,
        decision=Decision.PROCEED_WITH_LIMITS,
        inputs_used=["nea_file"],
        excluded=["ghost"],
        texts=["ok"],
    )
    status = {c.name: c.passed for c in report.checks}
    assert status["issue_time_inputs"] and not status["inputs_known"]
    assert not report.passed


def test_sealed_and_operational_words() -> None:
    assert checks.forbidden_phrases(["the test period MAE is low"]) == ["sealed"]
    assert checks.forbidden_phrases(["an operational forecast"]) == ["operational"]
    assert checks.forbidden_phrases(["the test period stays sealed"]) == []


def test_coverage_check() -> None:
    assert checks.coverage_check("c", ["d1"], ["d1"]).passed
    bad = checks.coverage_check("c", ["d1", "m1"], ["d1", "x9"])
    assert not bad.passed and "missing ['m1']" in bad.detail and "unknown ['x9']" in bad.detail


def test_rule_critic_on_the_frozen_cases() -> None:
    cases = load_cases(Path(ROOT / "examples" / "assess" / "critic-cases.json"))
    seeded = load_seeded(Path(ROOT / "examples" / "assess" / "critic-case-evidence.json"))
    pkgs = {p: package(p) for p in "abcd"}
    scores, totals = run_bench(cases, pkgs, lambda c, pkg: rule_critique(c.plan, pkg), seeded)
    # m41-v3 policy on the frozen m41-v2 labels: 5 of 12. Case D-f3 is labelled with the m41-v2
    # class subgroup_deterioration; the m41-v3 rule raises overall_deterioration there. The
    # recorded m41-v2 rule result (6 of 12) is unchanged.
    assert totals["faults_detected_raw"] == 5 and totals["clean_with_high_finding"] == 0
    d_f3 = next(s for s in scores if s.case == "D-f3")
    assert not d_f3.detected_raw
    assert totals["faults_detected"] <= totals["faults_detected_raw"]
    assert totals["unsupported_findings"] == 0
    unusable = run_bench(cases[:2], pkgs, lambda c, pkg: None, seeded)[1]
    assert unusable["usable"] == 0 and summary(scores)["cases"] == 24


def test_seeded_evidence_ids_exist_in_their_packages() -> None:
    cases = {c.id: c for c in load_cases(Path(ROOT / "examples" / "assess" / "critic-cases.json"))}
    seeded = load_seeded(Path(ROOT / "examples" / "assess" / "critic-case-evidence.json"))
    assert set(seeded) == {k for k, c in cases.items() if c.label != "clean"}
    for cid, ids in seeded.items():
        assert set(ids) <= checks.ids_of(package(cases[cid].package)), cid


@pytest.mark.parametrize(
    ("evidence", "cited", "raw", "detected"),
    [
        (["tcn.mae"], {"tcn.mae": 4.711}, True, True),
        (["tcn.mae"], {"tcn.mae": 9.9}, True, False),  # wrong value: unsupported
        (["persist.mae"], {}, True, False),  # backed, but not the seeded evidence
        (["no.such.id"], {}, True, False),  # unknown id
    ],
)
def test_detection_needs_backed_seeded_evidence(
    evidence: list[str], cited: dict[str, float], raw: bool, detected: bool
) -> None:
    case = next(
        c
        for c in load_cases(Path(ROOT / "examples" / "assess" / "critic-cases.json"))
        if c.id == "A-f1"
    )
    f = finding("c1", "neural_unjustified", evidence, cited=cited)
    crit = CritiqueV1.model_validate({"verdict": "concerns", "findings": [f]})
    got = score(case, crit, package("a"), ["tcn.mae", "tcn.skill"])
    assert (got.detected_raw, got.detected) == (raw, detected)


def _s(
    usable: int, detected: int, high: int, findings: int = 10, unsupported: int = 0
) -> dict[str, Any]:
    return {
        "usable": usable,
        "faults_detected": detected,
        "clean_with_high_finding": high,
        "findings": findings,
        "unsupported_findings": unsupported,
    }


def test_choose_critic_follows_the_protocol() -> None:
    from earthlab.assess.critic_bench import choose_critic, passes_gates

    rules = _s(24, 6, 0)
    s = {
        "rules": rules,
        "muse": _s(24, 11, 0),
        "a": _s(24, 7, 2, unsupported=1),
        "b": _s(24, 9, 5),
        "c": _s(10, 12, 0),
    }
    assert choose_critic(s, "muse") == ("a", True)
    assert passes_gates(s["a"], rules) == {
        "usable": True,
        "detected": True,
        "clean": True,
        "supported": True,
    }
    assert choose_critic({"rules": rules, "b": s["b"]}, "muse") == ("b", False)
    assert choose_critic({"rules": rules, "muse": s["muse"]}, "muse") == (None, False)


def _with_fact(prefix: str, fid: str, value: float | None, drop: bool = False) -> Any:
    pkg = package(prefix)
    facts = [f for f in pkg.facts if not (drop and f.id == fid)]
    if not drop:
        facts = [f.model_copy(update={"value": value}) if f.id == fid else f for f in facts]
    return pkg.model_copy(update={"facts": facts})


def _quality_flags(pkg: Any) -> list[list[str]]:
    return [f.evidence for f in policy.decide(pkg).flags if "hls.clear" in f.evidence]


def test_policy_reads_zero_as_a_value_and_reports_missing_facts() -> None:
    # smap.rq is 0 in package D; set it to 1 so only hls.clear decides the quality flag
    base = _with_fact("d", "smap.rq", 1.0)
    zero = base.model_copy(
        update={"facts": [f.model_copy(update={"value": 0.0}) if f.id == "hls.clear" else f
                          for f in base.facts]}
    )  # fmt: skip
    assert _quality_flags(zero) == [["hls.clear", "smap.rq"]]
    null = base.model_copy(
        update={"facts": [f.model_copy(update={"value": None}) if f.id == "hls.clear" else f
                          for f in base.facts]}
    )  # fmt: skip
    assert _quality_flags(null) == [] and "hls.clear" in policy.decide(null).missing_facts
    gone = base.model_copy(update={"facts": [f for f in base.facts if f.id != "hls.clear"]})
    result = policy.decide(gone)
    assert _quality_flags(gone) == [] and result.missing_facts == ["hls.clear"]
    assert all("hls.clear" not in f.evidence for f in result.flags)


@pytest.mark.parametrize(
    ("value", "drop", "flagged", "missing"),
    [(0.0, False, False, False), (3.0, False, True, False), (None, False, False, True),
     (None, True, False, True)],
)  # fmt: skip
def test_provenance_rule_zero_null_missing(
    value: float | None, drop: bool, flagged: bool, missing: bool
) -> None:
    pkg = _with_fact("b", "file.missing_region", value, drop)
    pkg = pkg.model_copy(
        update={"facts": [f.model_copy(update={"value": 0.0}) if f.id == "file.conflicts" else f
                          for f in pkg.facts]}
    )  # fmt: skip
    result = policy.decide(pkg)
    got = any(f.fault_class.value == "missing_observations" for f in result.flags)
    assert got is flagged and ("file.missing_region" in result.missing_facts) is missing


def _design_with_valid_quality_sources(**facts: float | str | None) -> Any:
    """Package D with HLS and SMAP made issue-time valid, so only quality facts decide."""
    pkg = package("d")
    sources = [
        s.model_copy(update={"availability": Availability.ISSUE_TIME_VALID})
        if s.id in ("hls", "smap")
        else s
        for s in pkg.sources
    ]
    kept = [f for f in pkg.facts if f.id not in facts]
    added = [
        f.model_copy(update={"value": facts[f.id]})
        for f in pkg.facts
        if f.id in facts and not isinstance(facts[f.id], str)
    ]
    return pkg.model_copy(update={"sources": sources, "facts": kept + added})


def test_measured_quality_makes_a_source_eligible() -> None:
    pkg = _design_with_valid_quality_sources(**{"hls.clear": 0.5, "smap.rq": 12.0})
    result = policy.decide(pkg)
    assert {"hls", "smap"} <= set(result.eligible_inputs) and result.missing_facts == []


@pytest.mark.parametrize("how", ["drop", None])
def test_missing_essential_quality_fact_never_permits_suitability(how: str | None) -> None:
    pkg = _design_with_valid_quality_sources(**{"hls.clear": how, "smap.rq": 12.0})
    result = policy.decide(pkg)
    assert "hls" not in result.eligible_inputs and "hls" in result.excluded_inputs
    assert "hls.clear" in result.missing_facts
    assert any(f.evidence == ["hls"] and "missing" in f.note for f in result.flags)
    report = checks.plan_report(
        "lead",
        pkg,
        decision=Decision.PROCEED_WITH_LIMITS,
        inputs_used=["nea_pm25", "hls"],
        excluded=[],
        texts=["Use HLS burn scars as an input."],
    )
    late = next(c for c in report.checks if c.name == "issue_time_inputs")
    assert not late.passed and late.detail == "hls"
