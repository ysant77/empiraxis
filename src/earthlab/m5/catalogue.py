"""Year-by-year coverage inventory from the NASA CMR catalogue. Metadata only: no data moves.

One hit count per product, year, season and area. The fetch function is injected, so tests run
offline. CMR returns the hit count in a response header; a query with page_size 0 returns no
granule records.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from earthlab.cases.models import BoundingBox

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
SEASON = ("-08-01T00:00:00Z", "-11-30T23:59:59Z")  # Aug-Nov, the haze season

# (name, short_name, version, nominal granules per day over the whole product, notes)
PRODUCTS: tuple[tuple[str, str, str, float | None], ...] = (
    ("HLSL30", "HLSL30", "2.0", None),
    ("HLSS30", "HLSS30", "2.0", None),
    ("SMAP_L3_36km", "SPL3SMP", "009", 1.0),
    ("SMAP_L3_9km", "SPL3SMP_E", "006", 1.0),
    ("IMERG_Early", "GPM_3IMERGHHE", "07", 48.0),
    ("IMERG_Late", "GPM_3IMERGHHL", "07", 48.0),
    ("IMERG_Final", "GPM_3IMERGHH", "07", 48.0),
    ("MAIAC_MCD19A2", "MCD19A2", "061", None),
    ("MCD64A1", "MCD64A1", "061", None),
)

Fetch = Callable[[str], tuple[dict[str, Any], int]]


@dataclass(frozen=True)
class CoverageRow:
    area: str
    product: str
    year: int
    scope: str  # "year" or "aug-nov"
    hits: int
    expected: float | None

    @property
    def fraction(self) -> float | None:
        return None if not self.expected else min(1.0, self.hits / self.expected)


def http_fetch(url: str) -> tuple[dict[str, Any], int]:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed https host
        hits = int(response.headers.get("CMR-Hits", "0"))
        return json.load(response), hits


def query_url(short_name: str, version: str, box: BoundingBox | None, start: str, end: str,
              page_size: int = 0) -> str:  # fmt: skip
    params = {"short_name": short_name, "version": version, "temporal": f"{start},{end}",
              "page_size": page_size}  # fmt: skip
    if box is not None:
        params["bounding_box"] = f"{box.min_lon},{box.min_lat},{box.max_lon},{box.max_lat}"
    return f"{CMR}?{urllib.parse.urlencode(params)}"


def _expected(per_day: float | None, days: int) -> float | None:
    return None if per_day is None else per_day * days


def inventory(areas: dict[str, BoundingBox | None], years: Iterable[int], fetch: Fetch = http_fetch,
              products: Iterable[tuple[str, str, str, float | None]] = PRODUCTS
              ) -> list[CoverageRow]:  # fmt: skip
    """Hit counts for every product, area, year and scope (whole year, August-November)."""
    rows: list[CoverageRow] = []
    for year in years:
        scopes = {
            "year": (f"{year}-01-01T00:00:00Z", f"{year}-12-31T23:59:59Z", 365),
            "aug-nov": (f"{year}{SEASON[0]}", f"{year}{SEASON[1]}", 122),
        }
        for area, box in areas.items():
            for name, short, version, per_day in products:
                for scope, (start, end, days) in scopes.items():
                    _, hits = fetch(query_url(short, version, box, start, end))
                    rows.append(CoverageRow(area, name, year, scope, hits,
                                            _expected(per_day, days)))  # fmt: skip
    return rows


def hls_cloud_summary(box: BoundingBox, start: str, end: str, short_name: str = "HLSL30",
                      fetch: Fetch = http_fetch) -> dict[str, float | int]:  # fmt: skip
    """Scene count and cloud statistics from granule metadata. `cloud_cover` is the provider's
    percentage; it does not measure smoke haze."""
    data, hits = fetch(query_url(short_name, "2.0", box, start, end, page_size=200))
    clouds = [float(e["cloud_cover"]) for e in data["feed"]["entry"] if e.get("cloud_cover")
              is not None]  # fmt: skip
    if not clouds:
        return {"scenes": hits, "with_cloud_value": 0, "mean_cloud": float("nan"),
                "scenes_le_20": 0}  # fmt: skip
    return {"scenes": hits, "with_cloud_value": len(clouds),
            "mean_cloud": sum(clouds) / len(clouds),
            "scenes_le_20": sum(1 for c in clouds if c <= 20.0)}  # fmt: skip
