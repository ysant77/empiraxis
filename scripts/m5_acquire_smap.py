"""Download pilot SMAP L3 (SPL3SMP v009, 36 km) daily granules and write receipts.

Usage: EARTHDATA_TOKEN=... uv run python scripts/m5_acquire_smap.py DATA_ROOT YYYY-MM-DD...
The token comes from the environment only. Cap: 40 MB per file.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from earthlab.m5 import acquire as A
from earthlab.m5.contracts import DataRole, ProductPin

PIN = ProductPin(
    dataset_id="smap-spl3smp-v009", product="SPL3SMP", version="009",
    provider="NASA NSIDC DAAC", licence="NASA Earth science data, no restrictions on use",
    licence_url="https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance",
    role=DataRole.ESTIMATE,
)  # fmt: skip
CAP = 40_000_000


def main() -> int:
    root = Path(sys.argv[1]).expanduser()
    receipts = []
    for day in sys.argv[2:]:
        date.fromisoformat(day)
        links = A.granule_links("SPL3SMP", "009", f"{day}T00:00:00Z", f"{day}T23:59:59Z", ".h5")
        if len(links) != 1:
            print(f"{day}: expected one granule, found {len(links)}")
            return 1
        receipts.append(A.acquire_one(links[0], root, PIN, CAP))
        print(day, receipts[-1].bytes, receipts[-1].sha256[:12])
    name = f"smap_{sys.argv[2]}_{sys.argv[-1]}.json"
    A.write_receipts(receipts, root / "receipts" / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
