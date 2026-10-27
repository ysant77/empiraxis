from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA, DatasetFactory
from pydantic import ValidationError

from earthlab.contracts import ALL_REGIONS, SGT, TimeWindow
from earthlab.data.nea_pm25 import Pm25Dataset
from earthlab.data.snapshot import open_snapshot
from earthlab.science.episode import summarize
from earthlab.verify.claims import Check, Claim, Verdict
from earthlab.verify.recompute import IndependentSource, SourceHashError
from earthlab.verify.verifier import Verifier

HAZE = {"start": "2015-09-01T00:00", "end": "2015-11-01T00:00"}


@pytest.fixture(scope="module")
def verifier() -> Verifier:
    snapshot, path = open_snapshot(REPO_DATA)
    return Verifier(IndependentSource.from_file(path, snapshot.sha256))


def claim(**fields: Any) -> Claim:
    return Claim.model_validate({**HAZE, "statement": "Observed value.", **fields})


def test_true_peak_is_supported_and_false_peak_rejected(verifier: Verifier) -> None:
    good = verifier.verify(claim(kind="peak_region", region="west", value=471))
    assert good.verdict == Verdict.SUPPORTED and good.observed == "west at 471"
    bad = verifier.verify(claim(kind="peak_region", region="central"))
    assert bad.verdict == Verdict.CONTRADICTED and "west" in bad.reason
    wrong_value = verifier.verify(claim(kind="peak_region", region="west", value=300))
    assert wrong_value.verdict == Verdict.CONTRADICTED


def test_region_max_checks_value_and_hour(verifier: Verifier) -> None:
    at = "2015-10-19T23:00"
    assert verifier.verify(claim(kind="region_max", region="west", value=471, at=at)).verdict == (
        Verdict.SUPPORTED
    )
    wrong_hour = verifier.verify(
        claim(kind="region_max", region="west", value=471, at="2015-10-19T22:00")
    )
    assert wrong_hour.verdict == Verdict.CONTRADICTED and "2015-10-19T23:00" in wrong_hour.reason
    assert verifier.verify(claim(kind="region_max", region="west", value=470)).verdict == (
        Verdict.CONTRADICTED
    )


def test_causal_forecast_and_health_language_is_unsupported(verifier: Verifier) -> None:
    for text in (
        "Fires in Sumatra caused the west peak.",
        "PM2.5 will rise again next year.",
        "Air was unhealthy; people should stay indoors.",
        "The west station read 471.",
        "PSI reached 471.",
    ):
        result = verifier.verify(claim(kind="peak_region", region="west", statement=text))
        assert result.verdict == Verdict.UNSUPPORTED and result.check == Check.LANGUAGE


def test_counts_and_mean(verifier: Verifier) -> None:
    missing = verifier.verify(claim(kind="missing_hours", region="north", value=0))
    assert missing.verdict == Verdict.SUPPORTED
    above = verifier.verify(claim(kind="hours_above", region="west", threshold=470, value=1))
    assert above.verdict == Verdict.SUPPORTED
    result = verifier.verify(claim(kind="region_mean", region="west", value=0))
    assert result.verdict == Verdict.CONTRADICTED
    assert isinstance(result.observed, float)
    close = verifier.verify(
        claim(kind="region_mean", region="west", value=round(result.observed, 1))
    )
    assert close.verdict == Verdict.SUPPORTED


def test_verifier_agrees_with_tool_path(verifier: Verifier, real_dataset: Pm25Dataset) -> None:
    """Two independent code paths must agree on every regional mean and max."""
    window = TimeWindow(start=datetime(2015, 9, 1), end=datetime(2015, 11, 1))
    for region in ALL_REGIONS:
        summary = summarize(real_dataset, window, region)
        checks = [
            claim(kind="region_mean", region=region.value, value=summary.mean),
            claim(kind="region_max", region=region.value, value=summary.max, at=summary.max_at),
        ]
        assert [r.verdict for r in verifier.verify_all(checks)] == [Verdict.SUPPORTED] * 2


def test_sparse_window_is_insufficient(make_data_dir: DatasetFactory) -> None:
    snapshot, path = open_snapshot(make_data_dir(["1/9/2015 0:00,10,20,30,40,50"]))
    sparse = Verifier(IndependentSource.from_file(path, snapshot.sha256))
    result = sparse.verify(
        Claim(
            kind="region_max",
            region="north",
            start=datetime(2015, 9, 1, tzinfo=SGT),
            end=datetime(2015, 9, 2, tzinfo=SGT),
            value=10,
            statement="North peaked at 10.",
        )
    )
    assert result.verdict == Verdict.INSUFFICIENT_DATA and result.check == Check.COVERAGE


def test_claim_shape_rules() -> None:
    with pytest.raises(ValidationError, match="needs a value"):
        claim(kind="region_max", region="west")
    with pytest.raises(ValidationError, match="threshold"):
        claim(kind="hours_above", region="west", value=3)
    with pytest.raises(ValidationError, match="'at'"):
        claim(kind="region_mean", region="west", value=3, at="2015-09-01T00:00")
    with pytest.raises(ValidationError):
        claim(kind="peak_region", region="west", statement="x" * 301)


def test_hash_mismatch_refused(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("1hr_pm25,north\n", encoding="utf-8")
    with pytest.raises(SourceHashError):
        IndependentSource.from_file(path, "0" * 64)


def test_bad_rows_are_skipped_by_independent_reader(make_data_dir: DatasetFactory) -> None:
    snapshot, path = open_snapshot(
        make_data_dir(["bad,1,2,3,4,5", "1/9/2015 0:00,x,-1,3,4,5", "1/9/2015 0:00,9,9,9,9,9"])
    )
    source = IndependentSource.from_file(path, snapshot.sha256)
    window = TimeWindow(start=datetime(2015, 9, 1), end=datetime(2015, 9, 1, 1))
    north, expected = source.series(ALL_REGIONS[0], window)
    assert north == [] and expected == 1
    east, _ = source.series(ALL_REGIONS[2], window)
    assert [v for _, v in east] == [3.0]


def test_naive_claim_times_do_not_depend_on_host_time_zone(
    verifier: Verifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a naive 'at' was read in the host zone, so CI (UTC) disagreed with SGT."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    try:
        result = verifier.verify(
            claim(kind="region_max", region="west", value=471, at="2015-10-19T23:00")
        )
        assert result.verdict == Verdict.SUPPORTED
        aware = claim(kind="region_max", region="west", value=471, at="2015-10-19T15:00Z")
        assert verifier.verify(aware).verdict == Verdict.SUPPORTED
    finally:
        monkeypatch.undo()
        time.tzset()
