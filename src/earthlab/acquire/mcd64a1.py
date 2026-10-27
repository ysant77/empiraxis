"""MCD64A1 v6.1 monthly burned area from Google Earth Engine, in the native MODIS grid.

Each month is exported as one GeoTIFF with all five bands as int16 in the native
sinusoidal projection (SR-ORG:6974, about 463.3 m pixels), clipped to the study box.
Earth Engine masks BurnDate wherever no burn was mapped, so a masked cell can be
unburned or unmapped. Masked cells are written as -1, never 0, and the QA bits (land,
valid data) decide which they are. Before the download, Earth Engine computes its own
pixel counts and pixel-area sums over the same box on the same grid; these are
recorded as an independent reference for the local computation.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from earthlab.cases.models import BoundingBox

COLLECTION = "MODIS/061/MCD64A1"
BANDS = ("BurnDate", "Uncertainty", "QA", "FirstDay", "LastDay")
FILL = -1
QA_LAND = 1  # bit 0: land grid cell
QA_VALID = 2  # bit 1: enough valid reflectance data to map the cell


def month_image(ee: Any, first: date, end: date) -> Any:
    images = ee.ImageCollection(COLLECTION).filterDate(first.isoformat(), end.isoformat())
    if images.size().getInfo() != 1:
        raise RuntimeError(f"expected one MCD64A1 image for {first:%Y-%m}")
    return ee.Image(images.first()).select(list(BANDS))


def native_grid(image: Any) -> dict[str, Any]:
    """CRS and affine transform of the product's own grid; exports reuse it exactly."""
    info: dict[str, Any] = image.select("BurnDate").projection().getInfo()
    return {"crs": info["crs"], "crs_transform": info["transform"]}


def region(ee: Any, box: BoundingBox) -> Any:
    """The study box as a planar lon/lat rectangle (pixel centres inside it count)."""
    corners = [box.min_lon, box.min_lat, box.max_lon, box.max_lat]
    return ee.Geometry.Rectangle(corners, "EPSG:4326", False)


def download_url(ee: Any, image: Any, box: BoundingBox, grid: dict[str, Any]) -> str:
    filled = image.unmask(FILL).toInt16()
    params = {
        "region": region(ee, box),
        "crs": grid["crs"],
        "crs_transform": grid["crs_transform"],
        "format": "GEO_TIFF",
        "filePerBand": False,
    }
    url: str = filled.getDownloadURL(params)
    return url


def reference_stats(ee: Any, image: Any, box: BoundingBox, grid: dict[str, Any]) -> dict[str, Any]:
    """Earth Engine's own counts on the same grid and box, computed server side."""
    burn = image.select("BurnDate").unmask(FILL)
    qa = image.select("QA").unmask(0)
    land = qa.bitwiseAnd(QA_LAND).gt(0)
    valid = land.And(qa.bitwiseAnd(QA_VALID).gt(0))
    burned = burn.gt(0).And(valid)
    layers = ee.Image.cat(
        ee.Image.constant(1).rename("all"),
        burn.eq(FILL).rename("burndate_masked"),
        image.select("QA").mask().Not().rename("qa_masked"),
        land.rename("land"),
        valid.rename("valid"),
        burned.rename("burned_valid"),
        burn.gt(0).rename("burned_any"),
        ee.Image.pixelArea().updateMask(burned).rename("burned_valid_m2"),
    )
    sums = layers.reduceRegion(
        reducer=ee.Reducer.sum().unweighted(),
        geometry=region(ee, box),
        crs=grid["crs"],
        crsTransform=grid["crs_transform"],
        maxPixels=10_000_000,
    ).getInfo()
    return {
        "pixels_in_box": int(sums["all"]),
        "burndate_masked_pixels": int(sums["burndate_masked"]),
        "qa_masked_pixels": int(sums["qa_masked"]),
        "land_pixels": int(sums["land"]),
        "valid_land_pixels": int(sums["valid"]),
        "burned_valid_pixels": int(sums["burned_valid"]),
        "burned_any_pixels": int(sums["burned_any"]),
        "burned_valid_area_m2": float(sums["burned_valid_m2"] or 0.0),
        "method": "ee reduceRegion, unweighted sum, native grid, pixel centres inside the box",
    }
