"""Reduce IMERG Early half-hour granules to H1 corridor means, one day at a time.

Usage: EARTHDATA_TOKEN=... uv run python scripts/m5_imerg_early_series.py DATA_ROOT FIRST LAST
Each granule is downloaded, reduced to three corridor mean rates (mm/h) and deleted. The
receipt keeps its SHA-256 and size. Total download is capped at 23 GB (owner approval for
about 22 GB, 2026-11-03). The run resumes: days already in the CSV are skipped.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from earthlab.m5 import acquire as A
from earthlab.m5 import imerg_series as S
from earthlab.m5.contracts import AcquisitionReceipt
from earthlab.m5.imerg import pin
from earthlab.m5.imerg_series import granule_start

TOTAL_CAP = 23_000_000_000
FILE_CAP = 15_000_000


def one_day(root: Path, day: date) -> tuple[S.Series, list[AcquisitionReceipt]]:
    links = A.granule_links("GPM_3IMERGHHE", "07", f"{day}T00:00:00Z", f"{day}T23:59:59Z", ".HDF5")
    rows: S.Series = {}
    receipts = []
    for url in links:
        r = A.acquire_one(url, root, pin("early"), FILE_CAP)
        path = Path(r.local_path)
        rows[granule_start(path.name)] = S.reduce_granule(path)
        path.unlink()
        receipts.append(r)
    return rows, receipts


def logged_bytes(log: Path) -> int:
    if not log.exists():
        return 0
    return sum(json.loads(line)["bytes"] for line in log.read_text().splitlines())


def main() -> int:
    root = Path(sys.argv[1]).expanduser()
    first, last = date.fromisoformat(sys.argv[2]), date.fromisoformat(sys.argv[3])
    csv_path = root / "derived" / "imerg_early_corridors.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    done = {s.date() for s in S.load_series(csv_path)} if csv_path.exists() else set()
    log = root / "receipts" / f"imerg_early_series_{first}_{last}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    total = logged_bytes(log)
    day = first
    while day <= last:
        if day not in done:
            if total > TOTAL_CAP:
                print("total cap reached")
                return 1
            rows, receipts = one_day(root, day)
            S.write_rows(csv_path, rows)
            with log.open("a", encoding="utf-8") as fh:
                fh.writelines(r.model_dump_json() + "\n" for r in receipts)
            total += sum(r.bytes for r in receipts)
            print(day, len(rows), total, flush=True)
        day += timedelta(days=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
