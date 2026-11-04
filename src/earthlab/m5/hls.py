"""HLS L30 v2.0 reader: a 30 m UTM tile band, its Fmask, and point sampling by lon/lat.

Reflectance is stored as int16 with scale 0.0001 and fill -9999; Fmask is uint8 with fill 255.
Fill becomes NaN (reflectance) or "no data" (Fmask). A tile that straddles the equator uses a
northern-hemisphere UTM zone with negative northings; this reader takes the hemisphere from
the file's GeoAscii text. Landsat 8 bands: B04 red, B05 NIR, B07 SWIR2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tifffile
from numpy.typing import NDArray
from pyproj import Transformer

REFLECTANCE_FILL = -9999
REFLECTANCE_SCALE = 1e-4
FMASK_FILL = 255
_ZONE = re.compile(r"UTM Zone (\d+), (Northern|Southern) Hemisphere")


class HlsFormatError(ValueError):
    """The file is not an HLS v2 UTM GeoTIFF this reader understands."""


@dataclass(frozen=True)
class Tile:
    data: NDArray[np.generic]
    x0: float
    y0: float
    pixel_m: float
    epsg: int

    def index(self, lon: NDArray[np.float64], lat: NDArray[np.float64]
              ) -> tuple[NDArray[np.int64], NDArray[np.int64], NDArray[np.bool_]]:  # fmt: skip
        """Row, column and an in-tile flag for each lon/lat point."""
        x, y = Transformer.from_crs(4326, self.epsg, always_xy=True).transform(lon, lat)
        col = np.floor((np.asarray(x) - self.x0) / self.pixel_m).astype(np.int64)
        row = np.floor((self.y0 - np.asarray(y)) / self.pixel_m).astype(np.int64)
        h, w = self.data.shape
        return row, col, (row >= 0) & (row < h) & (col >= 0) & (col < w)

    def sample(self, lon: NDArray[np.float64], lat: NDArray[np.float64]) -> NDArray[np.float64]:
        """Values at the points as float; NaN outside the tile or on fill."""
        row, col, inside = self.index(lon, lat)
        out = np.full(len(row), np.nan)
        out[inside] = self.data[row[inside], col[inside]]
        return out


def _open(path: Path) -> Tile:
    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        if not isinstance(page, tifffile.TiffPage):
            raise HlsFormatError(f"{path.name}: first page is not a full TIFF page")
        tags = {t.name: t.value for t in page.tags.values()}
        data = page.asarray()
    scale, tie = tags.get("ModelPixelScaleTag"), tags.get("ModelTiepointTag")
    match = _ZONE.search(str(tags.get("GeoAsciiParamsTag", "")))
    if scale is None or tie is None or match is None or data.ndim != 2:
        raise HlsFormatError(f"{path.name}: missing georeferencing or not a 2-D band")
    if scale[0] != scale[1]:
        raise HlsFormatError(f"{path.name}: pixels are not square")
    zone, north = int(match.group(1)), match.group(2) == "Northern"
    return Tile(data=data, x0=tie[3], y0=tie[4], pixel_m=float(scale[0]),
                epsg=(32600 if north else 32700) + zone)  # fmt: skip


def read_reflectance(path: Path) -> Tile:
    """Surface reflectance in [0, 1]-ish units; fill is NaN."""
    tile = _open(path)
    values = np.where(
        tile.data == REFLECTANCE_FILL, np.nan, tile.data.astype(np.float64) * REFLECTANCE_SCALE
    )
    return Tile(values.astype(np.float64), tile.x0, tile.y0, tile.pixel_m, tile.epsg)


def read_fmask(path: Path) -> Tile:
    """Fmask bytes as uint8; fill stays 255 and must be checked by the caller."""
    tile = _open(path)
    return Tile(tile.data.astype(np.uint8), tile.x0, tile.y0, tile.pixel_m, tile.epsg)
