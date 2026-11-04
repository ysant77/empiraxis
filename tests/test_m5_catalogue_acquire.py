"""CMR inventory and acquisition steps with fake network functions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from earthlab.cases.models import BoundingBox
from earthlab.m5 import acquire as A
from earthlab.m5 import catalogue as C
from earthlab.m5.contracts import DataRole, ProductPin

BOX = BoundingBox(min_lon=113.8, min_lat=-3.2, max_lon=114.8, max_lat=-2.0)
PIN = ProductPin(dataset_id="d", product="p", version="1", provider="x", licence="l",
                 licence_url="u", role=DataRole.ESTIMATE)  # fmt: skip


def test_query_url_carries_box_and_zero_page_size() -> None:
    url = C.query_url("HLSL30", "2.0", BOX, "2015-08-01T00:00:00Z", "2015-11-30T23:59:59Z")
    assert "bounding_box=113.8%2C-3.2%2C114.8%2C-2.0" in url and "page_size=0" in url
    assert "bounding_box" not in C.query_url("X", "1", None, "a", "b")


def test_inventory_counts_every_product_year_and_scope() -> None:
    calls: list[str] = []

    def fetch(url: str) -> tuple[dict[str, Any], int]:
        calls.append(url)
        return {}, 7

    rows = C.inventory({"kal": BOX}, [2015, 2016], fetch, products=C.PRODUCTS[:2] + C.PRODUCTS[4:5])
    assert len(rows) == 2 * 1 * 3 * 2 == len(calls)
    imerg = [r for r in rows if r.product == "IMERG_Early"]
    assert imerg[0].expected == 48.0 * 365 and imerg[0].fraction == pytest.approx(7 / (48 * 365))
    assert next(r for r in rows if r.product == "HLSL30").fraction is None


def test_hls_cloud_summary_uses_provider_values_only() -> None:
    entries = [{"cloud_cover": "10"}, {"cloud_cover": "50"}, {}]

    def fetch(url: str) -> tuple[dict[str, Any], int]:
        return {"feed": {"entry": entries}}, 3

    got = C.hls_cloud_summary(BOX, "a", "b", fetch=fetch)
    assert got["scenes"] == 3 and got["with_cloud_value"] == 2
    assert got["mean_cloud"] == 30.0 and got["scenes_le_20"] == 1
    empty = C.hls_cloud_summary(BOX, "a", "b", fetch=lambda u: ({"feed": {"entry": []}}, 0))
    assert empty["with_cloud_value"] == 0 and empty["mean_cloud"] != empty["mean_cloud"]


def test_granule_links_keep_https_data_links_with_suffix() -> None:
    entry = {"links": [
        {"rel": "http://esipfed.org/ns/fedsearch/1.1/data#", "href": "s3://b/x.h5"},
        {"rel": "http://esipfed.org/ns/fedsearch/1.1/data#", "href": "https://h/x.h5"},
        {"rel": "http://esipfed.org/ns/fedsearch/1.1/data#", "href": "https://h/x.xml"},
        {"rel": "other", "href": "https://h/y.h5"},
    ]}  # fmt: skip
    seen: list[str] = []

    def get(url: str) -> dict[str, Any]:
        seen.append(url)
        return {"feed": {"entry": [entry]}}

    assert A.granule_links("S", "1", "t0", "t1", ".h5", bbox="1,2,3,4", get=get) == [
        "https://h/x.h5"
    ]
    assert "bounding_box" in seen[0] and "temporal" in seen[0]
    A.granule_links("S", "1", "", "", ".tif", name="HLS.x", get=get)
    assert "readable_granule_name=HLS.x" in seen[1] and "temporal" not in seen[1]


def test_acquire_one_and_write_receipts(tmp_path: Path) -> None:
    def fake(url: str, target: Path, cap: int) -> tuple[str, int]:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"abc")
        return "ab" * 32, 3

    now = datetime(2026, 11, 3, tzinfo=UTC)
    r = A.acquire_one("https://h/dir/f.h5", tmp_path, PIN, 10, fake, now)
    assert r.receipt_id == "d:f.h5" and r.local_path.endswith("raw/d/f.h5") and r.bytes == 3
    out = tmp_path / "rec" / "r.json"
    A.write_receipts([r], out)
    assert json.loads(out.read_text())[0]["sha256"] == "ab" * 32
