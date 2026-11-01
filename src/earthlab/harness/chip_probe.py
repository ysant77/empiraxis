"""Read the real facts of one HLS burn-scar training chip, for the S4 gate.

The archive is read as a stream and is never changed or deleted. One chip and its mask are
copied to a sample folder. The probe reads TIFF tags only. It does not load model weights.
"""

from __future__ import annotations

import math
import re
import tarfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import tifffile

from earthlab.contracts import Strict

USER_DEFINED = 32767


class ChipFacts(Strict):
    file: str
    shape: tuple[int, ...]
    dtype: str
    band_count: int
    nodata: str | None
    crs_epsg: int | None
    crs_name: str | None
    origin_xy: tuple[float, float] | None
    pixel_size: tuple[float, ...] | None
    band_names_in_tags: tuple[str, ...]
    value_min: float
    value_max: float
    nodata_pixels: int
    mask_values: tuple[int, ...] = ()


class ArchiveSurvey(Strict):
    members: int
    suffix_counts: dict[str, int]
    splits: dict[str, int]
    sample_chip: str
    sample_mask: str | None


def _suffix(name: str) -> str:
    match = re.search(r"(\.[A-Za-z]+\.tif|_merged\.tif|\.tif)$", name)
    return match.group(1) if match else Path(name).suffix


def survey(archive: Path, dest: Path) -> ArchiveSurvey:
    """Count members by suffix and split, and copy the first chip and its mask to `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    splits: Counter[str] = Counter()
    chip: str | None = None
    mask: str | None = None
    total = 0
    with tarfile.open(archive, "r|gz") as tar:
        for member in tar:
            total += 1
            if not member.isfile():
                continue
            counts[_suffix(member.name)] += 1
            splits[member.name.split("/")[0]] += 1
            wanted = chip is None and member.name.endswith("_merged.tif")
            if not wanted and not (chip and mask is None and _pair(member.name, chip)):
                continue
            target = dest / Path(member.name).name
            data = tar.extractfile(member)
            if data is not None:
                target.write_bytes(data.read())
            chip, mask = (member.name, mask) if wanted else (chip, member.name)
    if chip is None:
        raise ValueError("no chip found in the archive")
    return ArchiveSurvey(
        members=total, suffix_counts=dict(counts), splits=dict(splits), sample_chip=chip,
        sample_mask=mask,
    )  # fmt: skip


def _pair(name: str, chip: str) -> bool:
    stem = Path(chip).name.replace("_merged.tif", "")
    return Path(name).name.startswith(stem) and "merged" not in name


def _tags(page: Any) -> dict[str, Any]:
    return {tag.name: tag.value for tag in page.tags.values()}


def probe(path: Path, nodata_value: float | None = None) -> ChipFacts:
    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        tags = _tags(page)
        data = tif.asarray()
        geo = tags.get("GeoKeyDirectoryTag")
        epsg = _epsg(geo)
        scale = tags.get("ModelPixelScaleTag")
        gdal_meta = str(tags.get("GDAL_METADATA", ""))
        names = tuple(re.findall(r'role="description"[^>]*>([^<]*)<', gdal_meta))
        fill = tags.get("GDAL_NODATA")
    nodata = str(fill).strip() if fill is not None else None
    wanted = nodata_value if nodata_value is not None else (float(nodata) if nodata else None)
    empty = _empty_pixels(data, wanted)
    bands = data.shape[-1] if data.shape[-1] <= 16 else data.shape[0]
    return ChipFacts(
        file=path.name, shape=tuple(int(n) for n in data.shape), dtype=str(data.dtype),
        band_count=int(bands) if data.ndim == 3 else 1, nodata=nodata, crs_epsg=epsg,
        crs_name=_crs_name(tags.get("GeoAsciiParamsTag")), origin_xy=_origin(tags),
        pixel_size=tuple(float(v) for v in scale) if scale is not None else None,
        band_names_in_tags=names, value_min=float(data.min()), value_max=float(data.max()),
        nodata_pixels=empty,
        mask_values=tuple(int(v) for v in np.unique(data)) if data.ndim == 2 else (),
    )  # fmt: skip


def _empty_pixels(data: Any, wanted: float | None) -> int:
    """Pixels whose every band holds the no-data value."""
    if wanted is None:
        return 0
    same = data == wanted
    return int(np.all(same, axis=-1).sum()) if data.ndim == 3 else int(same.sum())


def _epsg(geo: Any) -> int | None:
    if geo is None:
        return None
    values = list(geo)
    keys = {values[i]: values[i + 3] for i in range(4, len(values) - 3, 4)}
    code = keys.get(3072) or keys.get(2048)
    return None if code in (None, USER_DEFINED) else int(code)


def _crs_name(ascii_params: Any) -> str | None:
    return str(ascii_params).split("|")[0] if ascii_params else None


def _origin(tags: dict[str, Any]) -> tuple[float, float] | None:
    tie = tags.get("ModelTiepointTag")
    return (float(tie[3]), float(tie[4])) if tie is not None else None


def utm_to_lonlat(
    easting: float, northing: float, zone: int, north: bool = True
) -> tuple[float, float]:
    """WGS 84 longitude and latitude of a UTM point (Snyder series, metre-level error)."""
    a, f, k0 = 6378137.0, 1 / 298.257223563, 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    m = (northing if north else northing - 10_000_000.0) / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (
        mu + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
    )  # fmt: skip
    c1, t1 = ep2 * math.cos(phi1) ** 2, math.tan(phi1) ** 2
    n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = (easting - 500_000.0) / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d**2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
    )  # fmt: skip
    lon = (
        d - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120
    ) / math.cos(phi1)  # fmt: skip
    return math.degrees(lon) + (zone - 1) * 6 - 180 + 3, math.degrees(lat)
