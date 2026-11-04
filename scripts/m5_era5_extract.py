"""Write ERA5 manifests for one extra season and build the corridor-mean extracts.

Usage: m5_era5_extract.py DATA_ROOT YEAR
Reads DATA_ROOT/season/YEAR/era5/*.grib. Writes a manifest per level (hashes of the files
that M5 downloaded) and extract_10m.json and extract_850hpa.json next to the season folder.
Raw GRIB files stay outside Git.
"""

from __future__ import annotations

import sys
from pathlib import Path

from earthlab.digest import file_digest
from earthlab.haze.cli import build_extract
from earthlab.haze.grib import load_decoder
from earthlab.m5 import strict_json as sj

LEVELS = (("sl", "10m", "extract_10m.json"), ("pl", "850hPa", "extract_850hpa.json"))


def write_manifest(folder: Path, kind: str, year: int) -> Path:
    files = sorted(folder.glob(f"era5_{kind}_{year}_*.grib"))
    if not files:
        raise SystemExit(f"no era5_{kind}_{year}_*.grib in {folder}")
    entries = [{"file": f.name, "sha256": file_digest(f), "bytes": f.stat().st_size} for f in files]
    path = folder / f"era5-{kind}-season-{year}.manifest.json"
    path.write_text(sj.dumps({"asset_id": f"era5-{kind}-season-{year}", "files": entries}))
    return path


def main(root: Path, year: int) -> None:
    folder = root / "season" / str(year) / "era5"
    decoder = load_decoder()
    for kind, level, name in LEVELS:
        manifest = write_manifest(folder, kind, year)
        series = build_extract(manifest, level, decoder)
        out = root / "season" / str(year) / name
        out.write_text(sj.dumps({"series": [s.model_dump(mode="json") for s in series]}))
        print(f"{level}: {len(series)} boxes -> {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), int(sys.argv[2]))
