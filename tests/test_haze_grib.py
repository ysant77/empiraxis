"""GRIB decoding: a module-level fake ecCodes, and a round trip on a tiny synthetic GRIB.

The synthetic file is built at test time from ecCodes' own bundled samples, offline. That
test is skipped when the optional "haze" extra is not installed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np
import pytest

from earthlab.haze import cli
from earthlab.haze.grib import EccodesDecoder, UnsupportedGrid, load_decoder
from earthlab.haze.met import DecoderMissing

MISSING = 9999.0


def _message(**overrides: Any) -> dict[str, Any]:
    message: dict[str, Any] = {
        "gridType": "regular_ll",
        "Ni": 3,
        "Nj": 2,
        "latitudeOfFirstGridPointInDegrees": 2.0,
        "latitudeOfLastGridPointInDegrees": 1.0,
        "longitudeOfFirstGridPointInDegrees": 100.0,
        "longitudeOfLastGridPointInDegrees": 102.0,
        "bitmapPresent": 1,
        "missingValue": MISSING,
        "level": 0,
        "typeOfLevel": "surface",
        "shortName": "10u",
        "validityDate": 20150920,
        "validityTime": 600,
        "values": [1.0, 2.0, 3.0, 4.0, MISSING, 6.0],
    }
    message.update(overrides)
    return message


class FakeCodes:
    """Stands in for the eccodes module: each 'file' yields the queued messages."""

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages
        self.released: list[int] = []
        self._next = 0

    def codes_grib_new_from_file(self, stream: BinaryIO) -> int | None:
        if self._next >= len(self.messages):
            return None
        self._next += 1
        return self._next - 1

    def codes_get(self, gid: int, key: str) -> Any:
        return self.messages[gid][key]

    def codes_get_values(self, gid: int) -> list[float]:
        return list(self.messages[gid]["values"])

    def codes_release(self, gid: int) -> None:
        self.released.append(gid)


def test_fake_messages_decode_to_grid_fields(tmp_path: Path) -> None:
    path = tmp_path / "x.grib"
    path.write_bytes(b"synthetic")
    fake = FakeCodes([_message(), _message(shortName="u", typeOfLevel="isobaricInhPa", level=850)])
    surface, upper = list(EccodesDecoder(fake).fields(path))
    assert surface.short_name == "10u" and surface.level_hpa is None
    assert surface.valid_time == datetime(2015, 9, 20, 6, tzinfo=UTC)
    assert surface.lats.tolist() == [2.0, 1.0] and surface.lons.tolist() == [100.0, 101.0, 102.0]
    assert surface.values.shape == (2, 3) and np.isnan(surface.values[1, 1])
    assert upper.level_hpa == 850
    assert fake.released == [0, 1]


def test_longitudes_wrap_and_bitmap_off_keeps_values(tmp_path: Path) -> None:
    path = tmp_path / "x.grib"
    path.write_bytes(b"synthetic")
    message = _message(
        longitudeOfFirstGridPointInDegrees=358.0,
        longitudeOfLastGridPointInDegrees=360.0,
        bitmapPresent=0,
    )
    (field,) = EccodesDecoder(FakeCodes([message])).fields(path)
    assert field.lons.tolist() == [-2.0, -1.0, 0.0]
    assert field.values[1, 1] == MISSING


def test_non_regular_grid_is_refused_and_released(tmp_path: Path) -> None:
    path = tmp_path / "x.grib"
    path.write_bytes(b"synthetic")
    fake = FakeCodes([_message(gridType="reduced_gg")])
    with pytest.raises(UnsupportedGrid, match="reduced_gg"):
        list(EccodesDecoder(fake).fields(path))
    assert fake.released == [0]


@pytest.mark.parametrize("error", [ImportError, RuntimeError])
def test_missing_decoder_names_the_extra(error: type[Exception]) -> None:
    def importer(name: str) -> Any:
        raise error(f"no {name}")

    with pytest.raises(DecoderMissing, match="uv sync --extra haze"):
        load_decoder(importer)


def _write_synthetic_grib(codes: Any, path: Path) -> None:
    """Two tiny GRIB1 messages from ecCodes' bundled samples: 10 m u and 850 hPa u."""
    with path.open("wb") as out:
        for sample, short_name, level in (
            ("regular_ll_sfc_grib1", "10u", None),
            ("regular_ll_pl_grib1", "u", 850),
        ):
            gid = codes.codes_grib_new_from_samples(sample)
            try:
                for key, value in (
                    ("Ni", 3),
                    ("Nj", 2),
                    ("latitudeOfFirstGridPointInDegrees", 2.0),
                    ("latitudeOfLastGridPointInDegrees", 1.0),
                    ("longitudeOfFirstGridPointInDegrees", 100.0),
                    ("longitudeOfLastGridPointInDegrees", 102.0),
                    ("iDirectionIncrementInDegrees", 1.0),
                    ("jDirectionIncrementInDegrees", 1.0),
                    ("dataDate", 20150920),
                    ("dataTime", 600),
                    ("shortName", short_name),
                ):
                    codes.codes_set(gid, key, value)
                if level is not None:
                    codes.codes_set(gid, "level", level)
                codes.codes_set_values(gid, [1.5, 2.5, 3.5, 4.5, 5.5, 6.5])
                codes.codes_write(gid, out)
            finally:
                codes.codes_release(gid)


def test_synthetic_grib_round_trip_and_extract(tmp_path: Path) -> None:
    codes = pytest.importorskip("eccodes")
    path = tmp_path / "synthetic.grib"
    _write_synthetic_grib(codes, path)
    surface, upper = list(load_decoder().fields(path))
    assert (surface.short_name, surface.level_hpa) == ("10u", None)
    assert (upper.short_name, upper.level_hpa) == ("u", 850)
    assert surface.valid_time == datetime(2015, 9, 20, 6, tzinfo=UTC)
    assert np.allclose(surface.values, [[1.5, 2.5, 3.5], [4.5, 5.5, 6.5]], atol=0.01)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = tmp_path / "synthetic-era5.manifest.json"
    manifest.write_text(
        json.dumps({"asset_id": "synthetic-era5", "files": [{"file": path.name, "sha256": digest}]})
    )
    series = cli.build_extract(manifest, "850hPa", load_decoder())
    assert [s.box_id for s in series] == ["box-a", "box-b", "box-c"]
    assert series[0].sources[0].sha256 == digest
