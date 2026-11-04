"""Download pilot HLS L30 v2.0 bands (B04, B05, B07, Fmask) for named granules; write receipts.

Usage: EARTHDATA_TOKEN=... uv run python scripts/m5_acquire_hls.py DATA_ROOT GRANULE...
Cap: 40 MB per file. The token comes from the environment only.
"""

from __future__ import annotations

import sys
from pathlib import Path

from earthlab.m5 import acquire as A
from earthlab.m5.contracts import DataRole, ProductPin

PIN = ProductPin(
    dataset_id="hlsl30-v2.0", product="HLSL30", version="2.0", provider="NASA LP DAAC",
    licence="NASA Earth science data, no restrictions on use",
    licence_url="https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance",
    role=DataRole.OBSERVATION,
)  # fmt: skip
BANDS = ("B04", "B05", "B07", "Fmask")
CAP = 40_000_000


def main() -> int:
    root = Path(sys.argv[1]).expanduser()
    receipts = []
    for name in sys.argv[2:]:
        links = A.granule_links("HLSL30", "2.0", "", "", ".tif", name=name)
        for band in BANDS:
            hit = [u for u in links if u.endswith(f".{band}.tif")]
            if len(hit) != 1:
                print(f"{name} {band}: expected one link, found {len(hit)}")
                return 1
            receipts.append(A.acquire_one(hit[0], root, PIN, CAP))
            print(name, band, receipts[-1].bytes)
    A.write_receipts(receipts, root / "receipts" / "hls_pilot.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
