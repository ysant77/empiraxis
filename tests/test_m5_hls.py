"""HLS reader on a tiny synthetic GeoTIFF: scale, fill, hemisphere and point sampling."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

from earthlab.m5.hls import HlsFormatError, read_fmask, read_reflectance


def write(
    path: Path, data: np.ndarray, ascii_zone: str = "UTM Zone 50, Northern Hemisphere"
) -> None:
    extratags = [
        (33550, "d", 3, (30.0, 30.0, 0.0), True),
        (33922, "d", 6, (0.0, 0.0, 0.0, 199980.0, -300000.0, 0.0), True),
        (34737, "s", 0, ascii_zone + "|", True),
    ]
    tifffile.imwrite(path, data, extratags=extratags)


def test_reflectance_is_scaled_and_fill_is_nan(tmp_path: Path) -> None:
    arr = np.array([[1000, -9999], [2500, 0]], dtype=np.int16)
    write(tmp_path / "b.tif", arr)
    tile = read_reflectance(tmp_path / "b.tif")
    assert tile.epsg == 32650 and tile.pixel_m == 30.0
    assert tile.data[0, 0] == pytest.approx(0.1) and np.isnan(tile.data[0, 1])
    assert tile.data[1, 1] == 0.0  # a real zero reflectance is kept; only the fill is missing


def test_southern_hemisphere_zone_and_bad_files(tmp_path: Path) -> None:
    write(tmp_path / "s.tif", np.zeros((2, 2), np.int16), "UTM Zone 49, Southern Hemisphere")
    assert read_reflectance(tmp_path / "s.tif").epsg == 32749
    tifffile.imwrite(tmp_path / "bad.tif", np.zeros((2, 2), np.int16))
    with pytest.raises(HlsFormatError):
        read_reflectance(tmp_path / "bad.tif")


def test_sampling_by_lon_lat_and_outside_tile(tmp_path: Path) -> None:
    arr = np.arange(16, dtype=np.int16).reshape(4, 4)
    write(tmp_path / "f.tif", arr.astype(np.uint8))
    tile = read_fmask(tmp_path / "f.tif")
    assert tile.data.dtype == np.uint8
    from pyproj import Transformer

    # centre of pixel (row 1, col 2): x = 199980 + 2.5*30, y = -300000 - 1.5*30
    lon, lat = Transformer.from_crs(32650, 4326, always_xy=True).transform(
        199980 + 75.0, -300000 - 45.0
    )
    got = tile.sample(np.array([lon, lon + 1.0]), np.array([lat, lat]))
    assert got[0] == arr[1, 2] and np.isnan(got[1])
