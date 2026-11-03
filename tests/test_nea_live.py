"""NEA real-time capture: typed provenance, units as published, an append-only log, no retries."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from earthlab.acquire.nea_live import CATALOGUE, CaptureLog, capture, parse

FIXTURES = Path(__file__).parent / "fixtures" / "nea_live"
NOW = datetime(2026, 11, 3, 0, 40, tzinfo=UTC)


def raw(product: str) -> bytes:
    return (FIXTURES / f"{product}.json").read_bytes()


def test_pm25_keeps_region_publication_time_and_unit() -> None:
    rows = parse("pm25", raw("pm25"), NOW, "https://example.org/pm25")
    assert {r.place_id for r in rows} == {"north", "south", "east", "west", "central"}
    assert all(r.issued_time is not None and r.issued_time > r.event_time for r in rows)
    assert {r.unit for r in rows} == {"ug/m3"} and rows[0].latitude is not None


def test_station_units_stay_as_published() -> None:
    wind = parse("wind-speed", raw("wind-speed"), NOW, "u")
    rain = parse("rainfall", raw("rainfall"), NOW, "u")
    assert {r.unit for r in wind} == {"knots"} and {r.period for r in rain} == {"5 min total"}
    assert all(r.issued_time is None for r in wind)  # the source states no publication time
    assert CATALOGUE["wind-direction"].note.startswith("a bearing")


def test_a_failed_response_is_refused() -> None:
    with pytest.raises(ValueError, match="not a success"):
        parse("pm25", json.dumps({"code": 1, "errorMsg": "x"}).encode(), NOW, "u")


def test_the_log_keeps_the_first_value_and_appends_a_correction(tmp_path: Path) -> None:
    log = CaptureLog(tmp_path / "log.jsonl")
    rows = parse("pm25", raw("pm25"), NOW, "u")
    assert log.append(rows)["first"] == 5
    assert log.append(rows)["repeat"] == 5
    changed = rows[0].model_copy(update={"value": (rows[0].value or 0) + 7})
    assert CaptureLog(log.path).append([changed]) == {"first": 0, "correction": 1, "repeat": 0}
    lines = [json.loads(x) for x in log.path.read_text().splitlines()]
    assert [x["kind"] for x in lines] == ["first"] * 5 + ["correction"]
    assert lines[0]["value"] == rows[0].value


def test_capture_waits_between_requests_and_never_retries(tmp_path: Path) -> None:
    calls: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path.rsplit("/", 1)[-1])
        if calls[-1] == "rainfall":
            return httpx.Response(503)
        return httpx.Response(200, content=raw(calls[-1]))

    waits: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(answer))
    log = CaptureLog(tmp_path / "log.jsonl")
    assert capture(log, ("pm25", "wind-speed"), client, waits.append)["pm25"]["first"] == 5
    assert waits == [2.0]
    with pytest.raises(httpx.HTTPStatusError):
        capture(log, ("rainfall",), client, waits.append)
    assert calls == ["pm25", "wind-speed", "rainfall"]


def test_a_day_capture_asks_for_that_date_and_only_for_pm25(tmp_path: Path) -> None:
    seen: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url.params.get("date")))
        return httpx.Response(200, content=raw("pm25"))

    client = httpx.Client(transport=httpx.MockTransport(answer))
    log = CaptureLog(tmp_path / "log.jsonl")
    capture(log, ("pm25",), client, day=date(2026, 11, 3))
    assert seen == ["2026-11-03"]
    with pytest.raises(ValueError, match="pm25 only"):
        capture(log, ("pm25", "rainfall"), client, day=date(2026, 11, 3))


def test_a_day_capture_follows_pagination_to_the_end(tmp_path: Path) -> None:
    body = json.loads(raw("pm25"))
    pages = [dict(body, data=dict(body["data"], paginationToken="next")), body]
    asked: list[str | None] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.params.get("paginationToken"))
        return httpx.Response(200, content=json.dumps(pages[len(asked) - 1]).encode())

    client = httpx.Client(transport=httpx.MockTransport(answer))
    out = capture(CaptureLog(tmp_path / "log.jsonl"), ("pm25",), client, lambda _: None,
                  day=date(2026, 11, 3))  # fmt: skip
    assert asked == [None, "next"] and out["pm25"] == {"first": 5, "correction": 0, "repeat": 5}
