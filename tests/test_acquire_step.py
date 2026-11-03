"""The in-run acquisition: typed proposal, signed approval, bounded capture, QA against source."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from earthlab.forecast.dataset import load_grid
from earthlab.harness.acquire_step import (
    ENDPOINT,
    AcquisitionConfig,
    AcquisitionProposal,
    check,
    execute,
)
from earthlab.harness.lifecycle import Lifecycle
from earthlab.team import resources as res

ROOT = Path(__file__).resolve().parents[1]
GRID, _ = load_grid(ROOT / "data" / "nea" / "Historical1hrPM2.5.csv")
KEY = "test-operator-key"
# The published 2019-06-01 00:00 SGT values, which the local file also holds.
DAY = {"code": 0, "data": {"regionMetadata": [], "items": [{
    "timestamp": "2019-06-01T00:00:00+08:00", "updatedTimestamp": "2019-06-01T00:30:00+08:00",
    "readings": {"pm25_one_hourly": {"north": 12, "south": 6, "east": 5, "west": 11,
                                     "central": 9}}}]}}  # fmt: skip


def proposal(*days: date) -> AcquisitionProposal:
    return AcquisitionProposal(operation="capture_nea_day", dates=days, reason="Check the file.")


def approved_store(root: Path, url: str = ENDPOINT, approve: bool = True) -> None:
    desk = res.ResourceDesk(root)
    desk.open(res.ResourceRequestV1(
        request_id="nea-qa-1", parent_task_id="test", purpose="Three days of PM2.5 for QA.",
        asset="NEA PM2.5 history", url=url, max_bytes=1_000_000,
        content_types=("application/json",), license_terms="Singapore Open Data Licence",
        expires_utc=datetime.now(UTC) + timedelta(hours=2), scientific_need="QA of the file.",
        risk="none",
    ))  # fmt: skip
    desk.review("nea-qa-1", "geospatial_engineer", "test", True, "Fits.")
    desk.review("nea-qa-1", "product_manager", "test", True, "Fits.")
    desk.decide("nea-qa-1", approve, KEY, "owner")


def client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=json.dumps(DAY).encode())))  # fmt: skip


@pytest.mark.parametrize(
    ("days", "ok"),
    [((date(2019, 6, 1),), True), ((date(2024, 1, 1),), False), ((date(2013, 1, 1),), False),
     ((date(2019, 6, 1), date(2019, 6, 1)), False), ((), False)],
)  # fmt: skip
def test_the_proposal_is_typed_and_cannot_reach_the_sealed_period(
    days: tuple[date, ...], ok: bool
) -> None:
    assert (check(proposal(*days)) == []) is ok


def test_no_approval_means_a_recorded_refusal(tmp_path: Path) -> None:
    config = AcquisitionConfig("nea-qa-1", tmp_path / "store", client())
    receipt = execute(proposal(date(2019, 6, 1)), config, tmp_path / "out", GRID)
    assert receipt.state == "refused" and receipt.requests == 0
    assert not (tmp_path / "out").exists()


def test_an_approval_for_another_endpoint_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(res.OPERATOR_KEY_ENV, KEY)
    approved_store(tmp_path / "store", url="https://example.org/other")
    config = AcquisitionConfig("nea-qa-1", tmp_path / "store", client())
    receipt = execute(proposal(date(2019, 6, 1)), config, tmp_path / "out", GRID)
    assert receipt.state == "refused" and "another endpoint" in receipt.reason


def test_an_approved_capture_is_logged_and_checked_against_the_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(res.OPERATOR_KEY_ENV, KEY)
    approved_store(tmp_path / "store")
    config = AcquisitionConfig("nea-qa-1", tmp_path / "store", client())
    receipt = execute(proposal(date(2019, 6, 1)), config, tmp_path / "out", GRID)
    assert receipt.state == "acquired" and receipt.requests == 1 and receipt.bytes > 0
    assert (receipt.values, receipt.matched, receipt.mismatched) == (5, 5, 0)
    view = res.ResourceDesk(tmp_path / "store").view("nea-qa-1")
    assert view.fetched is not None


def test_acquired_is_an_optional_state_between_profiled_and_planned(tmp_path: Path) -> None:
    life = Lifecycle(tmp_path)
    for state in ("scoped", "profiled", "acquired", "planned"):
        life.move(state, "controller")
    assert life.state == "planned"
