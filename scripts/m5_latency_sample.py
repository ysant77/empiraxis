"""Measure current publication latency of IMERG runs from CMR metadata (no credentials).

Latency = production or insert time minus the end of the granule. This covers the latest 40
granules of today's service. It does not measure the 2015 archive, whose insert times are
reprocessing dates. Output: docs/m5/results/m5_latency_sample.json
"""

from __future__ import annotations

import json
import statistics
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

CMR = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
RUNS = {"imerg_early": "GPM_3IMERGHHE", "imerg_late": "GPM_3IMERGHHL"}


def parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def sample(short_name: str) -> dict[str, object]:
    query = {"short_name": short_name, "version": "07", "sort_key": "-start_date", "page_size": 40}
    with urllib.request.urlopen(  # noqa: S310
        f"{CMR}?{urllib.parse.urlencode(query)}", timeout=60
    ) as resp:
        items = json.load(resp)["items"]
    produced, inserted = [], []
    for item in items:
        umm = item["umm"]
        end = parse(umm["TemporalExtent"]["RangeDateTime"]["EndingDateTime"])
        made = parse(umm["DataGranule"]["ProductionDateTime"])
        added = parse(next(d["Date"] for d in umm["ProviderDates"] if d["Type"] == "Insert"))
        produced.append((made - end).total_seconds() / 3600)
        inserted.append((added - end).total_seconds() / 3600)
    stats = {}
    for name, hours in (("production_minus_end_h", produced), ("insert_minus_end_h", inserted)):
        stats[name] = {"min": min(hours), "median": statistics.median(hours), "max": max(hours)}
    return {"short_name": short_name, "granules": len(items), **stats}


def main() -> int:
    record = {
        "measured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "scope": "latest 40 granules of the current service; not the 2015 archive",
        "runs": {name: sample(short) for name, short in RUNS.items()},
        "firms_note": (
            "MODIS_SP is standard processing. The +3 h rule is an NRT assumption. Not measured."
        ),
    }
    Path("docs/m5/results/m5_latency_sample.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
