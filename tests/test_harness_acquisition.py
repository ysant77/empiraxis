"""The acquisition decision: steps in order, smallest request, and approval that is not assumed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from suitability_helpers import AOI, END, START, plan, profile

from earthlab.cases.models import BoundingBox
from earthlab.harness.acquisition import (
    BaselineGap,
    Extent,
    decide,
    marginal_value,
    smallest_request,
)

GAIN = BaselineGap(metric="mae", baseline_value=9.0, best_possible_gain=1.5)
ABSENT = {"local_state": "not_acquired", "local_sha256": None}
WIDE = BoundingBox(min_lon=95.0, min_lat=-6.0, max_lon=118.0, max_lat=4.0)


def wanted(**change: object) -> Extent:
    base = {"area": WIDE, "start": START - timedelta(days=30), "end": END, "bytes_estimate": 10**9}
    return Extent(**(base | change))


def test_a_verified_local_copy_needs_no_request() -> None:
    out = decide("t", profile(), plan(), GAIN, wanted())
    assert out.decision == "already_local" and out.request is None


def test_value_is_demonstrated_only_by_a_measured_gap() -> None:
    assert marginal_value(None) == "unproven"
    assert marginal_value(BaselineGap(metric="mae")) == "unproven"
    assert marginal_value(GAIN) == "demonstrated"
    assert marginal_value(BaselineGap(metric="mae", best_possible_gain=0.0)) == "none"


def test_the_request_is_cut_to_the_task_area_and_window() -> None:
    cut = smallest_request(wanted(), plan(), "demonstrated", None)
    assert cut is not None and cut.area == AOI and (cut.start, cut.end) == (START, END)
    assert cut.bytes_estimate < wanted().bytes_estimate
    far = BoundingBox(min_lon=10, min_lat=10, max_lon=11, max_lat=11)
    assert smallest_request(wanted(area=far), plan(), "demonstrated", None) is None
    late = datetime(2016, 1, 1, tzinfo=UTC)
    assert (
        smallest_request(
            wanted(start=late, end=late + timedelta(days=1)), plan(), "demonstrated", None
        )
        is None
    )


def test_unproven_value_gets_a_one_month_pilot() -> None:
    out = decide("t", profile(**ABSENT), plan(), None, wanted())
    assert out.decision == "pilot_needs_approval" and out.request is not None
    assert out.request.end - out.request.start == timedelta(days=31)
    assert out.route == ("data_specialist", "geospatial_lead", "product_manager", "human")
    assert [s.step for s in out.steps][-1] == "approval" and not out.steps[-1].passed
    assert out.post_transfer_steps == ("hash_verification", "quality_assurance", "registry")


def test_chat_approval_is_not_a_signed_record() -> None:
    out = decide("t", profile(**ABSENT), plan(), GAIN, wanted(), approval="chat_only")
    assert out.decision == "needs_approval" and "no signed record" in out.reasons[0]
    denied = decide("t", profile(**ABSENT), plan(), GAIN, wanted(), approval="denied")
    assert denied.decision == "needs_approval" and "denied" in denied.reasons[0]


def test_a_signed_approval_lets_the_transfer_proceed() -> None:
    out = decide("t", profile(**ABSENT), plan(), GAIN, wanted(), approval="signed")
    assert out.decision == "proceed_to_transfer" and out.route == ()
    covered = decide("t", profile(**ABSENT), plan(), GAIN, wanted(), covered_by_existing=True)
    assert covered.decision == "proceed_to_transfer"


def test_an_unsuitable_product_is_refused_before_value_is_weighed() -> None:
    unitless = profile(
        variables=(profile().variables[0].model_copy(update={"unit": "mph"}),), **ABSENT
    )
    out = decide("t", unitless, plan(), GAIN, wanted(), approval="signed")
    assert out.decision == "refuse" and out.alignment is not None
    assert [s.step for s in out.steps] == ["availability_query", "suitability"]
    forecast = decide("t", profile(**ABSENT), plan(arm="issue_time_forecast"), GAIN, wanted())
    assert forecast.decision == "refuse"


def test_no_room_to_gain_or_no_overlap_is_a_refusal() -> None:
    none = BaselineGap(metric="mae", baseline_value=1.0, best_possible_gain=0.0)
    assert decide("t", profile(**ABSENT), plan(), none, wanted()).decision == "refuse"
    far = BoundingBox(min_lon=10, min_lat=10, max_lon=11, max_lat=11)
    out = decide("t", profile(**ABSENT), plan(), GAIN, wanted(area=far))
    assert out.decision == "refuse" and "overlap" in out.reasons[0]
