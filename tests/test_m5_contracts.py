"""M5 contracts: strict fields, UTC times, digests, byte caps and availability bounds."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from earthlab.cases.models import BoundingBox
from earthlab.m5.contracts import (
    AcquisitionReceipt,
    Availability,
    DataRole,
    FeatureTransform,
    GridSpec,
    ProductPin,
    TimeKind,
    TimeSupport,
)

DIGEST = "ab" * 32
T0 = datetime(2015, 10, 19, 0, 0, tzinfo=UTC)
PIN = ProductPin(dataset_id="d", product="p", version="1", provider="x", licence="l",
                 licence_url="u", role=DataRole.OBSERVATION)  # fmt: skip


def receipt(**over: object) -> AcquisitionReceipt:
    base: dict[str, object] = dict(
        receipt_id="r", product=PIN, source_uri="https://x", local_path="p", sha256=DIGEST,
        bytes=10, retrieved_at_utc=T0, authority="a", byte_cap=100,
    )  # fmt: skip
    base.update(over)
    return AcquisitionReceipt(**base)


def test_receipt_accepts_a_complete_record() -> None:
    box = BoundingBox(min_lon=95, min_lat=-6, max_lon=118, max_lat=4)
    grid = GridSpec(crs="EPSG:4326", resolution_deg=0.1, footprint=box)
    assert receipt(grid=grid).sha256 == DIGEST


@pytest.mark.parametrize("bad", ["", "AB" * 32, "ab" * 31])
def test_receipt_refuses_a_bad_digest(bad: str) -> None:
    with pytest.raises(ValidationError):
        receipt(sha256=bad)


def test_receipt_refuses_unknown_fields_naive_times_and_cap_overrun() -> None:
    with pytest.raises(ValidationError):
        receipt(surprise=1)
    with pytest.raises(ValidationError, match="UTC"):
        receipt(retrieved_at_utc=datetime(2026, 1, 1))
    with pytest.raises(ValidationError, match="UTC"):
        receipt(retrieved_at_utc=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8))))
    with pytest.raises(ValidationError, match="byte cap"):
        receipt(bytes=101)


def test_accumulation_needs_its_duration() -> None:
    with pytest.raises(ValidationError):
        TimeSupport(kind=TimeKind.INTERVAL_ACCUMULATION)
    assert (
        TimeSupport(kind=TimeKind.INTERVAL_ACCUMULATION, accumulation_hours=1.0).stamp_marks
        == "unknown"
    )


def test_availability_bounds() -> None:
    nominal = Availability(observation_end_utc=T0, basis="nominal_latency", assumed_latency_hours=4)
    assert not nominal.usable_at(T0 + timedelta(hours=3, minutes=59))
    assert nominal.usable_at(T0 + timedelta(hours=4))
    recorded = Availability(observation_end_utc=T0, available_at_utc=T0 + timedelta(hours=1),
                            basis="recorded")  # fmt: skip
    assert recorded.usable_at(T0 + timedelta(hours=1))
    assert not recorded.usable_at(T0)
    hindsight = Availability(observation_end_utc=T0, basis="hindsight_only")
    assert not hindsight.usable_at(T0 + timedelta(days=3650))


def test_availability_refuses_inconsistent_records() -> None:
    with pytest.raises(ValidationError):
        Availability(
            observation_end_utc=T0, available_at_utc=T0 - timedelta(hours=1), basis="recorded"
        )
    with pytest.raises(ValidationError):
        Availability(observation_end_utc=T0, basis="recorded")
    with pytest.raises(ValidationError):
        Availability(observation_end_utc=T0, basis="nominal_latency")
    with pytest.raises(ValueError, match="UTC"):
        Availability(observation_end_utc=T0, basis="hindsight_only").usable_at(datetime(2020, 1, 1))


def test_transform_needs_source_digests() -> None:
    ok = FeatureTransform(feature_id="f", transform_version="1", formula="x", unit="mm",
                          source_sha256=(DIGEST,), data_class="hindsight")  # fmt: skip
    assert ok.source_sha256 == (DIGEST,)
    with pytest.raises(ValidationError):
        FeatureTransform(feature_id="f", transform_version="1", formula="x", unit="mm",
                         source_sha256=(), data_class="hindsight")  # fmt: skip
    with pytest.raises(ValidationError):
        FeatureTransform(feature_id="f", transform_version="1", formula="x", unit="mm",
                         source_sha256=("zz",), data_class="hindsight")  # fmt: skip
