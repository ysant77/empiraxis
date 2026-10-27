"""NASA FIRMS archived active-fire detections for a bounding box, through the area API.

The API returns at most five days per request, so a period is split into five-day chunks
and the CSV parts are joined under one header. The MAP_KEY comes from the environment
and never appears in a file, a log line or an error message.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

import httpx

from earthlab.cases.models import BoundingBox

API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
MAX_DAYS = 5  # the API answered "Expects [1..5]" on 2026-10-27
TIMEOUT_SECONDS = 120.0


def chunks(start: date, end: date) -> list[tuple[date, int]]:
    """(first day, day count) pairs covering [start, end), at most MAX_DAYS days each."""
    parts: list[tuple[date, int]] = []
    day = start
    while day < end:
        count = min(MAX_DAYS, (end - day).days)
        parts.append((day, count))
        day += timedelta(days=count)
    return parts


def request_url(key: str, source: str, box: BoundingBox, first: date, days: int) -> str:
    area = f"{box.min_lon},{box.min_lat},{box.max_lon},{box.max_lat}"
    return f"{API}/{key}/{source}/{area}/{days}/{first.isoformat()}"


def redact(text: str, key: str) -> str:
    return text.replace(key, "<MAP_KEY>") if key else text


def joined_csv(parts: list[str]) -> Iterator[bytes]:
    """One header, then the data rows of every part, in order."""
    header: str | None = None
    for part in parts:
        lines = part.strip("\n").split("\n")
        if not lines or not lines[0]:
            continue
        if header is None:
            header = lines[0]
            yield (header + "\n").encode()
        elif lines[0] != header:
            raise ValueError("FIRMS parts have different headers")
        for line in lines[1:]:
            yield (line + "\n").encode()


def fetch_parts(
    key: str, source: str, box: BoundingBox, start: date, end: date, client: httpx.Client
) -> list[str]:
    """Fetch every chunk. An HTTP error or a text error reply stops the download."""
    parts: list[str] = []
    for first, days in chunks(start, end):
        url = request_url(key, source, box, first, days)
        try:
            resp = client.get(url, timeout=TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise RuntimeError(redact(f"FIRMS request failed: {exc}", key)) from None
        body = resp.text
        if resp.status_code != 200 or not body.startswith("latitude"):
            raise RuntimeError(redact(f"FIRMS reply {resp.status_code}: {body[:200]}", key))
        parts.append(body)
    return parts
