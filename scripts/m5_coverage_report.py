"""Render docs/m5/M5_COVERAGE_INVENTORY.md from the CSV files in docs/m5/coverage."""

from __future__ import annotations

import csv
from pathlib import Path

COV = Path("docs/m5/coverage")
YEARS = [str(y) for y in range(2015, 2027)]


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in rows])


def hits_table(rows: list[dict[str, str]], area: str, scope: str) -> str:
    products = sorted({r["product"] for r in rows if r["area"] == area})
    out = []
    for p in products:
        by_year = {
            r["year"]: r["granule_hits"]
            for r in rows
            if r["area"] == area and r["product"] == p and r["scope"] == scope
        }
        out.append([p, *(by_year.get(y, "") for y in YEARS)])
    return table(["Product", *YEARS], out)


def hls_section(hls: list[dict[str, str]]) -> str:
    cols = ["Product", "Year", "Scenes", "Mean provider cloud %", "Scenes with cloud ≤ 20%"]
    keys = ("product", "year", "scenes", "mean_provider_cloud_pct", "scenes_le_20pct")
    return table(cols, [[r[k] for k in keys] for r in hls])


def nea_section(nea: list[dict[str, str]]) -> str:
    cols = ["Year", "Hours with a value per region (of grid hours)", "Missing fraction"]
    rows = []
    for y in sorted({r["year"] for r in nea}):
        mine = [r for r in nea if r["year"] == y]
        rows.append([y, " / ".join(r["hours_with_value"] for r in mine),
                     " / ".join(r["missing_fraction"] for r in mine)])  # fmt: skip
    return table(cols, rows)


INTRO = (
    "# M5 coverage inventory, 2015 to 2026\n\nBuilt from NASA CMR catalogue counts (metadata only; "
    "no granule was downloaded for this table) and from the local NEA file. 2026 is a partial "
    "year. NEA years from 2024 are sealed and are not reported. Counts are granules, not data "
    "quality. Regenerate with `scripts/m5_coverage_inventory.py`, `scripts/m5_nea_completeness.py` "
    "and `scripts/m5_coverage_report.py`.\n"
)
NOTE_KAL = (
    "\nHLSS30 has no 2015 granule: S30 starts in late 2015-11. MCD64A1 has one granule per month, "
    "so four in the season. SMAP shows 76 of about 122 daily granules in 2022.\n"
)
NOTE_GLOBAL = (
    "\nNominal count is 5,856 (48 per day for 122 days). IMERG V07 Final ends on 2025-09-30: it "
    "has 2,928 granules in 2025 and none in 2026. Early and Late continue.\n"
)
NOTE_HLS = (
    "`cloud_cover` is the provider's value. It does not measure smoke haze. In 2015 the Fmask "
    "high-aerosol flag covered more than 96% of the pilot pixels.\n"
)
NOTE_NEA = (
    "\nRegion order: north, south, east, west, central. Years 2016 and 2018 have the excluded "
    "labels listed in `forecast/dataset.py`.\n"
)
NOTE_OTHER = (
    "Counts for the Singapore receptor box and source boxes A, B and C are in "
    "`docs/m5/coverage/coverage_inventory.csv`. FIRMS and ERA5 have no CMR record; ERA5 covers "
    "1940 to now, the FIRMS MODIS archive covers 2000 to now.\n"
)


def main() -> int:
    rows = list(csv.DictReader((COV / "coverage_inventory.csv").open()))
    hls = list(csv.DictReader((COV / "hls_kalimantan_cloud.csv").open()))
    nea = list(csv.DictReader((COV / "nea_completeness.csv").open()))
    parts = [
        INTRO, "## Granules over the Kalimantan study box, August to November\n",
        hits_table(rows, "kalimantan_study_box", "aug-nov"), NOTE_KAL,
        "## Global gridded products, August to November (granules)\n",
        hits_table(rows, "global_grid", "aug-nov"), NOTE_GLOBAL,
        "## HLS L30 and S30 over the Kalimantan box, August to November\n", NOTE_HLS,
        hls_section(hls), "\n## NEA regional PM2.5 completeness (open years)\n",
        nea_section(nea), NOTE_NEA, "## Other areas\n", NOTE_OTHER,
    ]  # fmt: skip
    Path("docs/m5/M5_COVERAGE_INVENTORY.md").write_text("\n".join(parts), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
