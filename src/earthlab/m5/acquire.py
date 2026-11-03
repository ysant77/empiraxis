"""Resolve CMR granules to https links, download them under a cap and write receipts.

One function per step so tests can fake the network. A receipt is written only after the
file's size and SHA-256 are known. Raw files go to a data root outside Git.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from earthlab.m5 import fetch
from earthlab.m5.catalogue import CMR
from earthlab.m5.contracts import AcquisitionReceipt, ProductPin

AUTHORITY = (
    "Owner instruction relayed in the M5 session brief, 2026-11-03: small pilot downloads of "
    "free, openly licensed data are approved; any download over about 5 GB needs the owner. "
    "This is not a signed HumanApproval record."
)
Download = Callable[[str, Path, int], tuple[str, int]]


def _json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed https host
        data: dict[str, Any] = json.load(response)
        return data


def granule_links(short_name: str, version: str, start: str, end: str, suffix: str,
                  bbox: str | None = None, name: str | None = None,
                  get: Callable[[str], dict[str, Any]] = _json) -> list[str]:  # fmt: skip
    """https data links ending in `suffix` for granules in the time range (or one named granule)."""
    query = {"short_name": short_name, "version": version, "page_size": 200}
    if name:
        query["readable_granule_name"] = name
    else:
        query["temporal"] = f"{start},{end}"
        if bbox:
            query["bounding_box"] = bbox
    data = get(f"{CMR}?{urllib.parse.urlencode(query)}")
    links = [link["href"] for entry in data["feed"]["entry"] for link in entry.get("links", [])
             if link.get("rel", "").endswith("data#") and link["href"].startswith("https")
             and link["href"].endswith(suffix)]  # fmt: skip
    return sorted(links)


def acquire_one(url: str, root: Path, pin: ProductPin, byte_cap: int,
                download: Download = fetch.download, now: datetime | None = None,
                **extra: Any) -> AcquisitionReceipt:  # fmt: skip
    """Download one file, write `<file>.receipt.json` next to its receipt folder, return it."""
    target = root / "raw" / pin.dataset_id / Path(urllib.parse.urlparse(url).path).name
    sha, size = download(url, target, byte_cap)
    receipt = AcquisitionReceipt(
        receipt_id=f"{pin.dataset_id}:{target.name}", product=pin, source_uri=url,
        local_path=str(target), sha256=sha, bytes=size, byte_cap=byte_cap,
        retrieved_at_utc=now or datetime.now(UTC), authority=AUTHORITY, **extra,
    )  # fmt: skip
    return receipt


def write_receipts(receipts: list[AcquisitionReceipt], path: Path) -> None:
    """Write receipts as sorted, indented JSON. Local paths are made relative to the data root."""
    payload = [json.loads(r.model_dump_json()) for r in receipts]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
