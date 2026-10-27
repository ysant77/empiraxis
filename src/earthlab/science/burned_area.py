"""MCD64A1 mapped burned area for one month inside a study box (the tool's computation).

Definitions follow config/methods/mcd64a1_burned_area.yaml: a pixel is in the box when
its centre is; burned means BurnDate in the file's month on a valid land pixel; the
primary area sums each burned pixel's area on the WGS84 ellipsoid (pyproj geodesic
polygon of the pixel corners); the nominal area uses the product's sphere-based pixel.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date

import numpy as np
from pydantic import Field
from pyproj import Geod

from earthlab.cases.models import BoundingBox
from earthlab.contracts import Strict
from earthlab.data.mcd64a1 import Grid, MonthRaster

SPHERE_RADIUS_M = 6371007.181  # MODIS sinusoidal grid sphere
QA_LAND, QA_VALID = 1, 2
_WGS84 = Geod(ellps="WGS84")


class MonthSummary(Strict):
    month: str
    source_sha256: str
    pixels_in_box: int
    land_pixels: int
    valid_land_pixels: int
    valid_fraction: float = Field(ge=0, le=1)
    burned_pixels: int
    burned_pixels_near_edge: int
    burn_date_outside_month: int
    primary_area_m2: float
    nominal_area_m2: float
    min_valid_fraction: float
    gate_passed: bool

    @property
    def primary_area_ha(self) -> float:
        return self.primary_area_m2 / 1e4


def sinusoidal_to_lonlat(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat = np.degrees(y / SPHERE_RADIUS_M)
    lon = np.degrees(x / (SPHERE_RADIUS_M * np.cos(np.radians(lat))))
    return lon, lat


def pixel_centres(shape: tuple[int, int], grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    rows, cols = np.indices(shape)
    x = grid.x0 + (cols + 0.5) * grid.sx
    y = grid.y0 - (rows + 0.5) * grid.sy
    return sinusoidal_to_lonlat(x, y)


def in_box(lon: np.ndarray, lat: np.ndarray, box: BoundingBox) -> np.ndarray:
    return (lon >= box.min_lon) & (lon <= box.max_lon) & (lat >= box.min_lat) & (lat <= box.max_lat)


def near_edge(lon: np.ndarray, lat: np.ndarray, box: BoundingBox, grid: Grid) -> np.ndarray:
    """Pixels whose centre lies within one pixel width of the box edge."""
    metres_per_deg = SPHERE_RADIUS_M * np.pi / 180
    d_lon = (
        np.minimum(lon - box.min_lon, box.max_lon - lon) * metres_per_deg * np.cos(np.radians(lat))
    )
    d_lat = np.minimum(lat - box.min_lat, box.max_lat - lat) * metres_per_deg
    return np.minimum(d_lon / grid.sx, d_lat / grid.sy) < 1.0


def wgs84_pixel_area(row: int, col: int, grid: Grid) -> float:
    xs = np.array([col, col + 1, col + 1, col]) * grid.sx + grid.x0
    ys = grid.y0 - np.array([row, row, row + 1, row + 1]) * grid.sy
    lon, lat = sinusoidal_to_lonlat(xs, ys)
    area, _ = _WGS84.polygon_area_perimeter(lon, lat)
    return abs(float(area))


def month_doy_range(month: str) -> tuple[int, int]:
    year, mon = (int(part) for part in month.split("-"))
    first = date(year, mon, 1).timetuple().tm_yday
    return first, first + monthrange(year, mon)[1] - 1


def summarize_month(
    raster: MonthRaster, box: BoundingBox, min_valid_fraction: float
) -> MonthSummary:
    burn, qa = raster.bands["BurnDate"], raster.bands["QA"]
    lon, lat = pixel_centres(burn.shape, raster.grid)
    inside = in_box(lon, lat, box)
    land = inside & (qa >= 0) & ((qa & QA_LAND) > 0)
    valid = land & ((qa & QA_VALID) > 0)
    first, last = month_doy_range(raster.month)
    burned = valid & (burn >= first) & (burn <= last)
    outside_month = valid & (burn > 0) & ((burn < first) | (burn > last))
    rows, cols = np.nonzero(burned)
    primary = sum(
        wgs84_pixel_area(int(r), int(c), raster.grid) for r, c in zip(rows, cols, strict=True)
    )
    land_count, valid_count = int(land.sum()), int(valid.sum())
    fraction = valid_count / land_count if land_count else 0.0
    return MonthSummary(
        month=raster.month,
        source_sha256=raster.sha256,
        pixels_in_box=int(inside.sum()),
        land_pixels=land_count,
        valid_land_pixels=valid_count,
        valid_fraction=round(fraction, 6),
        burned_pixels=int(burned.sum()),
        burned_pixels_near_edge=int((burned & near_edge(lon, lat, box, raster.grid)).sum()),
        burn_date_outside_month=int(outside_month.sum()),
        primary_area_m2=round(primary, 1),
        nominal_area_m2=round(int(burned.sum()) * raster.grid.sx * raster.grid.sy, 1),
        min_valid_fraction=min_valid_fraction,
        gate_passed=fraction >= min_valid_fraction,
    )
