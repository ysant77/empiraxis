"""Download pilot IMERG V07 half-hourly granules for given UTC days and write receipts.

Usage: EARTHDATA_TOKEN=... uv run python scripts/m5_acquire_imerg.py DATA_ROOT RUN DAY...
RUN is `final` (GPM_3IMERGHH), `early` (GPM_3IMERGHHE) or `late` (GPM_3IMERGHHL).
Cap: 15 MB per file; files are fetched one at a time.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from earthlab.m5 import acquire as A
from earthlab.m5.contracts import DataRole, ProductPin

RUNS = {"final": "GPM_3IMERGHH", "early": "GPM_3IMERGHHE", "late": "GPM_3IMERGHHL"}
CAP = 15_000_000


def pin(run: str) -> ProductPin:
    return ProductPin(
        dataset_id=f"imerg-v07-{run}", product=RUNS[run], version="07", run=run,
        provider="NASA GES DISC", licence="NASA Earth science data, no restrictions on use",
        licence_url="https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance",
        role=DataRole.ESTIMATE,
    )  # fmt: skip


def main() -> int:
    root, run = Path(sys.argv[1]).expanduser(), sys.argv[2]
    receipts = []
    for day in sys.argv[3:]:
        date.fromisoformat(day)
        links = A.granule_links(RUNS[run], "07", f"{day}T00:00:00Z", f"{day}T23:59:59Z", ".HDF5")
        print(day, len(links), "granules", flush=True)
        for url in links:
            receipts.append(A.acquire_one(url, root, pin(run), CAP))
    A.write_receipts(receipts, root / "receipts" / f"imerg_{run}_{sys.argv[3]}_{sys.argv[-1]}.json")
    print(sum(r.bytes for r in receipts), "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
