"""The adversarial suite: each attack is refused and each valid control allowed, with a reason."""

from __future__ import annotations

from pathlib import Path

import pytest

from earthlab.evals.adversarial import load_suite, run_case

ROOT = Path(__file__).resolve().parents[1]
SUITE = load_suite(ROOT / "evals" / "adversarial_scientific_v1.yaml")


def test_the_suite_covers_all_fourteen_categories_with_attacks_and_controls() -> None:
    assert {c.category for c in SUITE.cases} == set(range(1, 15))
    assert {c.role for c in SUITE.cases} == {"attack", "control"}
    assert all((c.role == "attack") == (c.expected == "refuse") for c in SUITE.cases)


@pytest.mark.parametrize("case", SUITE.cases, ids=lambda c: c.id)
def test_each_case_has_the_expected_outcome(case: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    result = run_case(case)  # type: ignore[arg-type]
    assert result.observed == result.expected, result.evidence
