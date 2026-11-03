"""Write docs/m5/layers_manifest.json: the M5 layers, their state and their source digests.

Usage: uv run python scripts/m5_layers_manifest.py
Reads manifests and receipts already in the repository. Downloads nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from earthlab.m5.layers import LayerSpec, catalogue_json

KAL = Path("data/kalimantan-2015")
NASA = "NASA Earth science data; cite the product DOI and the DAAC."
ERA5_ATTR = "Contains modified Copernicus Climate Change Service information (ERA5)."
ERA5_PL_DIGESTS = (  # runs/haze-2015/era5 manifests, 850 hPa files (Sep, Oct)
    "6ffd4adbf55a958da91766f6957bcf1cedd076eabe73b022977a8d62dc96a070",
    "ee5f98abec07edb4e2b9dc4752909559419554f1b6f47caab5a87c0518a79756",
)
BASE = {"attribution": NASA, "hindsight": True}


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def _digests(manifest: Path) -> tuple[str, ...]:
    return tuple(f["sha256"] for f in json.loads(manifest.read_text())["files"])


def _receipt_digests(name: str) -> tuple[str, ...]:
    return tuple(r["sha256"] for r in json.loads(Path(f"docs/m5/receipts/{name}").read_text()))


def available_layers() -> list[LayerSpec]:
    nea = json.loads(Path("data/nea/manifest.json").read_text())
    firms = KAL / "firms-modis-sp-kalimantan-2015.manifest.json"
    mcd = KAL / "mcd64a1-061-kalimantan-2015.manifest.json"
    return [
        LayerSpec(
            layer_id="nea-pm25", title="NEA regional PM2.5", kind="series", state="available",
            product="NEA Historical 1-hr PM2.5", version="2026-10-20 snapshot", unit="ug/m3",
            first_utc=utc(2014, 3, 31, 17), last_utc=utc(2023, 12, 31, 15),
            attribution=nea["attribution"], hindsight=False, source_sha256=(nea["sha256"],),
            limits=("five regions, not stations", "label start or end of hour not stated",
                    "2024 onward is sealed and not listed"),
        ),
        LayerSpec(
            layer_id="era5-wind-850", title="ERA5 850 hPa wind (corridor means)",
            kind="vector_series", state="available", product="ERA5 pressure levels",
            version="final expver 1", unit="m/s", first_utc=utc(2015, 9, 1),
            last_utc=utc(2015, 10, 31, 23), attribution=ERA5_ATTR, hindsight=True,
            source_sha256=ERA5_PL_DIGESTS,
            limits=("reanalysis made later", "not the plume height", "box means, not a grid"),
        ),
        LayerSpec(
            layer_id="firms-modis", title="FIRMS MODIS active-fire detections", kind="points",
            state="available", product="FIRMS MODIS_SP", version="Collection 6.1",
            unit="detection; FRP in MW", first_utc=utc(2015, 9, 1), last_utc=utc(2015, 10, 30),
            source_sha256=_digests(firms), **BASE,
            limits=("thermal anomaly, not burned area or emissions",
                    "clouds and thick smoke hide fires"),
        ),
        LayerSpec(
            layer_id="mcd64a1-2015-09", title="MCD64A1 burned area, September 2015",
            kind="raster", state="available", product="MCD64A1", version="6.1",
            unit="day of year", first_utc=utc(2015, 9, 1), last_utc=utc(2015, 9, 30),
            source_sha256=_digests(mcd)[:1], **BASE,
            limits=("valid land 0.970", "mapped product, not ground truth"),
        ),
    ]  # fmt: skip


def withheld_layers() -> list[LayerSpec]:
    return [
        LayerSpec(
            layer_id="mcd64a1-2015-10", title="MCD64A1 burned area, October 2015", kind="raster",
            state="gated_out", product="MCD64A1", version="6.1", unit="day of year", **BASE,
            reason="valid land share 0.460 is below the 0.80 gate",
        ),
        LayerSpec(
            layer_id="hls-l30", title="HLS L30 surface reflectance", kind="raster",
            state="gated_out", product="HLSL30", version="2.0", unit="reflectance",
            first_utc=utc(2015, 9, 13), last_utc=utc(2015, 10, 15), **BASE,
            source_sha256=_receipt_digests("hls_pilot.json"),
            reason="HLS_not_eligible: 2.7% of the box is clear land on both dates; "
            "more than 96% of pixels carry the high-aerosol flag",
        ),
        LayerSpec(
            layer_id="smap-l3-36km", title="SMAP L3 soil moisture", kind="grid_series",
            state="gated_out", product="SPL3SMP", version="009", unit="m3/m3", **BASE,
            reason="SMAP_unsuitable: no recommended-quality retrieval in the Kalimantan box "
            "(0 of 78 retrieved cell-passes)",
        ),
        LayerSpec(
            layer_id="imerg-v07", title="GPM IMERG rainfall", kind="grid_series",
            state="blocked", product="GPM_3IMERGHH", version="07", unit="mm/h", **BASE,
            reason="GES DISC returned HTTP 403; the owner must authorise the "
            "NASA GESDISC DATA ARCHIVE app in Earthdata Login",
        ),
        LayerSpec(
            layer_id="maiac-aod", title="MAIAC aerosol optical depth", kind="grid_series",
            state="not_assessed", product="MCD19A2", version="061", unit="1", **BASE,
            reason="HDF4 reader not built; AOD is a column quantity, not surface PM2.5",
        ),
    ]  # fmt: skip


def main() -> int:
    text = catalogue_json(available_layers() + withheld_layers())
    Path("docs/m5/layers_manifest.json").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
