"""What the reader sees: values from the verifier, and no text that denies limits or vouches
for data quality without a supported claim. The wording comes from the first live runs."""

from __future__ import annotations

import pytest

from earthlab.agent.area_findings import AreaLedger
from earthlab.agent.findings import FindingsLedger
from earthlab.agent.limitations import LimitationArgs, ReasonCode
from earthlab.agent.rendered import verified_block
from earthlab.verify.answer_audit import audit_answer


@pytest.mark.parametrize(
    "text",
    [
        "Verified finding A1.1. Limitations stated: none.",
        "There are no known limitations.",
        "The result has no limitations.",
    ],
)
def test_text_may_not_deny_limitations(text: str) -> None:
    audit = audit_answer(text, {}, {"A1.1"})
    assert any("no limitations" in m for m in audit.misleading)


def test_the_method_limits_can_be_described() -> None:
    assert audit_answer("Mapped area has limitations (A1.1).", {}, {"A1.1"}).passed


@pytest.mark.parametrize(
    "text",
    [
        "The QA gate is passed, with a valid-data fraction near the high end.",
        "The month has high coverage.",
        "Coverage is sufficient for the month.",
    ],
)
def test_quality_wording_needs_a_supported_claim(text: str) -> None:
    assert not audit_answer(text, {}).passed
    assert audit_answer(text, {}, quality_bound=True).passed


@pytest.mark.parametrize(
    "text",
    [
        "Coverage is insufficient for the month.",
        "The quality gate did not pass, so no area is reported.",
        "The valid-data fraction is not high enough.",
    ],
)
def test_an_abstention_may_say_that_quality_failed(text: str) -> None:
    assert audit_answer(text, {}).passed


def test_an_empty_run_has_no_block() -> None:
    assert verified_block(FindingsLedger(), AreaLedger(), []) == ""


def test_a_declared_limitation_is_shown_without_method_limits() -> None:
    entry = LimitationArgs(
        reasons=[ReasonCode.INSUFFICIENT_VALID_DATA], explanation="Too few valid pixels."
    )
    block = verified_block(FindingsLedger(), AreaLedger(), [entry])
    assert "insufficient_valid_data" in block and "Method limits" not in block
