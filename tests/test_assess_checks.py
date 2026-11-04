from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from assess_fakes import ROOT, finding, package

from earthlab.assess import checks, policy
from earthlab.assess.contracts import Decision, FindingV1
from earthlab.assess.critic_bench import load_cases, rule_critique, run_bench, summary
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
    pkgs = {p: package(p) for p in "abcd"}
    scores, totals = run_bench(cases, pkgs, lambda c, pkg: rule_critique(c.plan, pkg))
    assert totals["faults_detected"] == 6 and totals["clean_with_high_finding"] == 0
    assert totals["unsupported_findings"] == 0
    unusable = run_bench(cases[:2], pkgs, lambda c, pkg: None)[1]
    assert unusable["usable"] == 0 and summary(scores)["cases"] == 24


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
