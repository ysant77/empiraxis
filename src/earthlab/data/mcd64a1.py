"""Open a pinned MCD64A1 month: check its hash against the manifest, read its five bands.

The reader refuses a file whose SHA-256 or grid differs from the manifest. It returns
raw int16 arrays; classification and area live in science/burned_area.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import tifffile

from earthlab.data.snapshot import SourceMismatchError
from earthlab.digest import file_digest

NODATA = -32768
BAND_ORDER = ("BurnDate", "Uncertainty", "QA", "FirstDay", "LastDay")


@dataclass(frozen=True)
class Grid:
    """North-up affine grid: x = x0 + col * sx, y = y0 - row * sy (metres, sinusoidal)."""

    x0: float
    y0: float
    sx: float
    sy: float

    @classmethod
    def from_affine(cls, transform: list[float]) -> Grid:
        sx, rot1, x0, rot2, neg_sy, y0 = transform
        if rot1 or rot2 or neg_sy >= 0:
            raise SourceMismatchError("grid must be north-up with no rotation")
        return cls(x0=x0, y0=y0, sx=sx, sy=-neg_sy)


@dataclass(frozen=True)
class MonthRaster:
    month: str
    file: str
    sha256: str
    grid: Grid
    bands: dict[str, np.ndarray]
    reference: dict[str, Any]


def aligned(file_affine: list[float], product_affine: list[float], tol: float = 1e-6) -> bool:
    """Same pixel size, no rotation, origin a whole number of pixels from the product's."""
    fx, fr1, fx0, fr2, fsy, fy0 = file_affine
    px, pr1, px0, pr2, psy, py0 = product_affine
    if abs(fx - px) > tol or abs(fsy - psy) > tol or fr1 or fr2 or pr1 or pr2:
        return False
    cols, rows = (fx0 - px0) / px, (fy0 - py0) / psy
    return abs(cols - round(cols)) < tol and abs(rows - round(rows)) < tol


def read_manifest(path: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return manifest


def _read_tiff(path: Path) -> tuple[np.ndarray, list[float]]:
    with tifffile.TiffFile(path) as tif:
        array = tif.asarray()
        page = tif.pages[0]
        if not isinstance(page, tifffile.TiffPage):
            raise SourceMismatchError(f"{path.name}: first page is not a full TIFF page")
        tags = {tag.name: tag.value for tag in page.tags.values()}
    if array.ndim != 3:
        raise SourceMismatchError(f"{path.name}: expected a 3-D band stack")
    if array.shape[0] == len(BAND_ORDER):
        array = np.moveaxis(array, 0, -1)
    matrix = tags.get("ModelTransformationTag")
    if matrix is None:
        raise SourceMismatchError(f"{path.name}: no GeoTIFF model transformation")
    affine = [matrix[0], matrix[1], matrix[3], matrix[4], matrix[5], matrix[7]]
    return array.astype(np.int32), affine


def load_month(data_dir: Path, manifest_name: str, month: str) -> MonthRaster:
    """The month's bands, after the file hash and the grid match the manifest. Fail closed."""
    manifest = read_manifest(data_dir / manifest_name)
    entries = [f for f in manifest["files"] if f.get("month") == month]
    if len(entries) != 1:
        raise SourceMismatchError(f"manifest has no single entry for month {month}")
    entry = entries[0]
    path = data_dir / entry["file"]
    actual = file_digest(path)
    if actual != entry["sha256"]:
        raise SourceMismatchError(f"{entry['file']}: sha256 {actual[:12]}... does not match")
    array, affine = _read_tiff(path)
    if not aligned(affine, entry["grid"]["crs_transform"]):
        raise SourceMismatchError(f"{entry['file']}: grid is not aligned with the product grid")
    if list(entry["bands"]) != list(BAND_ORDER) or array.shape[-1] != len(BAND_ORDER):
        raise SourceMismatchError(f"{entry['file']}: unexpected band layout")
    bands = {name: array[..., i] for i, name in enumerate(BAND_ORDER)}
    return MonthRaster(
        month=month,
        file=entry["file"],
        sha256=entry["sha256"],
        grid=Grid.from_affine(affine),
        bands=bands,
        reference=entry["reference"],
    )
