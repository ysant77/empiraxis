"""A small, rate-limited capture of official NEA real-time observations into an append-only log.

Five products from api-open.data.gov.sg: regional PM2.5 and station wind speed, wind direction,
rainfall and relative humidity. Each value keeps its own time, place, unit and averaging period,
the time it was fetched and the digest of the raw response. Units stay as published: wind speed
is in knots and rainfall is a five-minute total, not a rate. Station values are never joined to
the five PM2.5 regions here; that needs a documented spatial rule first.

The log is append-only. A later different value for the same product, place and time is kept
as a correction record next to the first one, never in its place.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import Field

from earthlab.contracts import Strict

BASE = "https://api-open.data.gov.sg/v2/real-time/api/"
MIN_INTERVAL_SECONDS = 2.0
Product = Literal["pm25", "wind-speed", "wind-direction", "rainfall", "relative-humidity"]


class ProductSpec(Strict):
    product: Product
    quantity: str
    unit: str
    period: str
    place: Literal["region", "station"]
    note: str = ""


CATALOGUE: dict[str, ProductSpec] = {
    "pm25": ProductSpec(product="pm25", quantity="PM2.5 mass concentration", unit="ug/m3",
                        period="1 h mean", place="region",
                        note="updatedTimestamp is the publication time"),
    "wind-speed": ProductSpec(product="wind-speed", quantity="wind speed", unit="knots",
                              period="1 min mean", place="station",
                              note="knots, not m/s: 1 knot is 0.514444 m/s"),
    "wind-direction": ProductSpec(product="wind-direction", quantity="wind-from direction",
                                  unit="degrees", period="1 min mean", place="station",
                                  note="a bearing; average u and v, never the angles"),
    "rainfall": ProductSpec(product="rainfall", quantity="rainfall total", unit="mm",
                            period="5 min total", place="station",
                            note="a total over 5 min, not a rate"),
    "relative-humidity": ProductSpec(product="relative-humidity", quantity="relative humidity",
                                     unit="percent", period="1 min mean", place="station"),
}  # fmt: skip


class Observation(Strict):
    """One published value with its provenance."""

    product: str
    place_id: str
    latitude: float | None = None
    longitude: float | None = None
    event_time: datetime
    issued_time: datetime | None = None  # publication time, when the source states one
    retrieved_at: datetime
    value: float | None
    unit: str
    period: str
    source_url: str
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["first", "correction"] = "first"


def _stations(data: dict[str, Any]) -> dict[str, tuple[float | None, float | None]]:
    return {
        s["id"]: (s.get("location", {}).get("latitude"), s.get("location", {}).get("longitude"))
        for s in data.get("stations", [])
    }


def _pm25(data: dict[str, Any], base: dict[str, Any]) -> Iterator[Observation]:
    places = {r["name"]: r.get("labelLocation", {}) for r in data.get("regionMetadata", [])}
    for item in data.get("items", []):
        readings = item.get("readings", {}).get("pm25_one_hourly", {})
        for region, value in readings.items():
            where = places.get(region, {})
            yield Observation(
                place_id=region, latitude=where.get("latitude"), longitude=where.get("longitude"),
                event_time=item["timestamp"], issued_time=item.get("updatedTimestamp"),
                value=value, **base,
            )  # fmt: skip


def parse(product: str, raw: bytes, retrieved_at: datetime, url: str) -> list[Observation]:
    """Typed observations from one raw response. A malformed response raises ValueError."""
    spec = CATALOGUE[product]
    body = json.loads(raw)
    if body.get("code") != 0 or "data" not in body:
        raise ValueError(f"{product}: the response is not a success")
    data = body["data"]
    base = {"product": product, "retrieved_at": retrieved_at, "unit": spec.unit,
            "period": spec.period, "source_url": url,
            "raw_sha256": hashlib.sha256(raw).hexdigest()}  # fmt: skip
    if spec.place == "region":
        return list(_pm25(data, base))
    where = _stations(data)
    return [
        Observation(place_id=r["stationId"], latitude=where.get(r["stationId"], (None, None))[0],
                    longitude=where.get(r["stationId"], (None, None))[1],
                    event_time=reading["timestamp"], value=r.get("value"), **base)
        for reading in data.get("readings", []) for r in reading.get("data", [])
    ]  # fmt: skip


class CaptureLog:
    """Append-only JSONL. The first value for a key stays; a changed later value is a correction."""

    def __init__(self, path: Path):
        self.path = path
        self._seen: dict[tuple[str, str, str], float | None] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                row = Observation.model_validate_json(line)
                self._seen.setdefault(self._key(row), row.value)

    @staticmethod
    def _key(row: Observation) -> tuple[str, str, str]:
        return row.product, row.place_id, row.event_time.isoformat()

    def append(self, rows: list[Observation]) -> dict[str, int]:
        counts = {"first": 0, "correction": 0, "repeat": 0}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as out:
            for row in rows:
                key = self._key(row)
                if key in self._seen and self._seen[key] == row.value:
                    counts["repeat"] += 1
                    continue
                kind: Literal["first", "correction"] = (
                    "correction" if key in self._seen else "first"
                )
                self._seen.setdefault(key, row.value)
                out.write(row.model_copy(update={"kind": kind}).model_dump_json() + "\n")
                counts[kind] += 1
        return counts


def capture(
    log: CaptureLog,
    products: tuple[str, ...] = tuple(CATALOGUE),
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, dict[str, int]]:
    """One request per product, at least MIN_INTERVAL_SECONDS apart. Nothing is retried."""
    own = client is None
    client = client or httpx.Client(timeout=20.0)
    out: dict[str, dict[str, int]] = {}
    try:
        for i, product in enumerate(products):
            if i:
                sleep(MIN_INTERVAL_SECONDS)
            url = BASE + CATALOGUE[product].product
            response = client.get(url)
            response.raise_for_status()
            rows = parse(product, response.content, datetime.now(UTC), url)
            out[product] = log.append(rows)
    finally:
        if own:
            client.close()
    return out
