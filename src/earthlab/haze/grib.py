"""Decode ERA5 GRIB messages into grid fields through ecCodes (optional extra "haze").

Only regular latitude/longitude grids are accepted. Missing values become NaN, never
zero. The valid time is the GRIB validity date and time, in UTC; for an accumulation
such as total precipitation it is the end of the accumulation hour.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from earthlab.haze.met import DecoderMissing, GridField

INSTALL_HINT = "uv sync --extra haze"


class UnsupportedGrid(ValueError):
    """The message is not on a regular latitude/longitude grid."""


def _valid_time(codes: Any, gid: Any) -> datetime:
    day = str(codes.codes_get(gid, "validityDate"))
    hhmm = f"{int(codes.codes_get(gid, 'validityTime')):04d}"
    return datetime.strptime(day + hhmm, "%Y%m%d%H%M").replace(tzinfo=UTC)


def _axes(codes: Any, gid: Any) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    ni, nj = int(codes.codes_get(gid, "Ni")), int(codes.codes_get(gid, "Nj"))
    lats = np.linspace(
        float(codes.codes_get(gid, "latitudeOfFirstGridPointInDegrees")),
        float(codes.codes_get(gid, "latitudeOfLastGridPointInDegrees")),
        nj,
    )
    lons = np.linspace(
        float(codes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")),
        float(codes.codes_get(gid, "longitudeOfLastGridPointInDegrees")),
        ni,
    )
    return lats, (lons + 180.0) % 360.0 - 180.0


def message_field(codes: Any, gid: Any) -> GridField:
    """One GRIB message as a GridField. Refuse any grid that is not regular_ll."""
    grid = str(codes.codes_get(gid, "gridType"))
    if grid != "regular_ll":
        raise UnsupportedGrid(f"grid type {grid} is not supported; expected regular_ll")
    lats, lons = _axes(codes, gid)
    values = np.asarray(codes.codes_get_values(gid), dtype=np.float64).reshape(lats.size, lons.size)
    if int(codes.codes_get(gid, "bitmapPresent")):
        values = np.where(values == float(codes.codes_get(gid, "missingValue")), np.nan, values)
    level = int(codes.codes_get(gid, "level"))
    on_pressure = str(codes.codes_get(gid, "typeOfLevel")) == "isobaricInhPa"
    return GridField(
        short_name=str(codes.codes_get(gid, "shortName")),
        level_hpa=level if on_pressure else None,
        valid_time=_valid_time(codes, gid),
        lats=lats,
        lons=lons,
        values=values,
    )


class EccodesDecoder:
    """GridDecoder over an ecCodes module (the real one, or a fake in tests)."""

    def __init__(self, codes: Any) -> None:
        self._codes = codes

    def fields(self, path: Path) -> Iterator[GridField]:
        codes = self._codes
        with path.open("rb") as stream:
            while (gid := codes.codes_grib_new_from_file(stream)) is not None:
                try:
                    yield message_field(codes, gid)
                finally:
                    codes.codes_release(gid)


def load_decoder(importer: Callable[[str], Any] = importlib.import_module) -> EccodesDecoder:
    """The ecCodes decoder, or DecoderMissing naming the extra to install."""
    try:
        codes = importer("eccodes")
    except (ImportError, RuntimeError) as exc:
        raise DecoderMissing(
            f"the GRIB decoder is not available ({type(exc).__name__}); run: {INSTALL_HINT}"
        ) from None
    return EccodesDecoder(codes)
