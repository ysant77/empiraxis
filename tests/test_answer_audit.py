from __future__ import annotations

from typing import Any

import pytest

from earthlab.safety.scope import question_out_of_scope
from earthlab.verify.answer_audit import audit_answer, text_numbers
from earthlab.verify.claims import Check, Claim, Verdict, VerificationResult

HAZE = {"start": "2015-09-01T00:00", "end": "2015-11-01T00:00"}


def result(kind: str, region: str, value: float, verdict: Verdict = Verdict.SUPPORTED) -> Any:
    raw = {**HAZE, "kind": kind, "region": region, "value": value, "statement": "Seen."}
    return VerificationResult(
        claim=Claim.model_validate(raw), verdict=verdict, check=Check.VALUE, reason=""
    )


FINDINGS = {
    "R1.1": result("peak_region", "west", 471),
    "R1.2": result("region_max", "central", 267),
    "R1.3": result("region_max", "east", 999, Verdict.CONTRADICTED),
}


def test_names_and_finding_ids_are_not_numbers() -> None:
    text = "PM2.5 in ug/m3 and µg/m³ is shown in R1.2 and R12.10; the 2015 peak was 471."
    assert text_numbers(text) == ["2015", "471"]


def test_spelled_out_numbers_are_numbers() -> None:
    """Observed in a live Muse run: 'far below nine hundred ninety-nine'."""
    assert text_numbers("far below nine hundred ninety-nine (R1.1)") == ["hundred", "ninety"]
    assert text_numbers("one region, two findings") == []


def test_a_clean_text_passes_and_problems_are_listed() -> None:
    assert audit_answer("West had the highest value (R1.1).", FINDINGS).passed
    bad = audit_answer("East peaked in Oct at 999 (R1.3); central was the cleanest.", FINDINGS)
    assert bad.problems() == [
        "numbers in the text (999); use the Findings",
        "dates in the text (Oct); use the Findings",
        "R1.3 is not a supported finding",
        "'cleanest' has no supported claim kind",
    ]


@pytest.mark.parametrize(
    ("text", "passed"),
    [
        # Observed in live Muse runs on 2026-10-27: denials, not assertions.
        ("Therefore, on observed data central is not the worst region in the window.", True),
        (
            "Therefore the colleague's claim that central had the highest hourly PM2.5 is "
            "not supported by the observed data.",
            True,
        ),
        ("Central had the highest value, not west.", False),
        ("Central had the highest value.", False),
    ],
)
def test_denied_superlatives_pass_and_asserted_ones_fail(text: str, passed: bool) -> None:
    assert audit_answer(text, FINDINGS).passed is passed


def test_superlative_without_a_region_and_ordinary_words_pass() -> None:
    text = "The highest values may reflect at least one smoke episode; the data show no cause."
    assert audit_answer(text, FINDINGS).passed


@pytest.mark.parametrize(
    "question",
    [
        "Could the 2015 fires have caused a heatwave in Kalimantan?",
        "How much tree-cover loss and deforestation followed the 2015 fires?",
        "Did fire-driven tree loss cause the heatwave?",
        "Was forest loss permanent land-use conversion or temporary fire damage?",
        "Did rainfall deficits precede the fires?",
        "Compare NEA data with third-party fire detections for October 2015.",
    ],
)
def test_neutral_research_questions_are_admitted(question: str) -> None:
    assert question_out_of_scope(question) is None


@pytest.mark.parametrize(
    "question",
    [
        "Is forest loss in Indonesia linked to government policy?",
        "Which political party should we blame for the haze?",
        "Was the air hazardous to breathe?",
    ],
)
def test_blame_and_advice_questions_are_refused(question: str) -> None:
    assert question_out_of_scope(question) is not None
