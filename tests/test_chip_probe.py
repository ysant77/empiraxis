"""Chip probe and S4 measurement on tiny synthetic GeoTIFF chips. No real archive is read."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import numpy as np
import pytest
import tifffile
from suitability_helpers import AOI

from earthlab.cases.models import BoundingBox
from earthlab.harness import gates
from earthlab.harness.chip_probe import probe, survey, utm_to_lonlat
from earthlab.harness.s4_measure import main, measure
from earthlab.harness.segmentation_gate import (
    Imagery,
    ReferenceMasks,
    Resources,
    SegmentationRequestV1,
    Weights,
    gate,
)

GEO = (1, 1, 0, 3, 1024, 0, 1, 1, 2048, 0, 1, 32767, 3072, 0, 1, 32767)
NAME = "subsetted_512x512_HLS.S30.T14SNB.2018215.v1.4"


def chip_data(bands: int = 6) -> bytes:
    data = np.full((32, 32, bands), 0.1, dtype=np.float32)
    data[0, 0, :] = 0.0
    buf = io.BytesIO()
    extra = [
        (34735, "H", len(GEO), GEO, True), (33550, "d", 3, (30.0, 30.0, 0.0), True),
        (33922, "d", 6, (0.0, 0.0, 0.0, 552840.0, 3661530.0, 0.0), True),
        (34737, "s", 31, "UTM Zone 14, Northern Hemisphere|", True),
        (42113, "s", 2, "0", True),
    ]  # fmt: skip
    tifffile.imwrite(buf, data, photometric="minisblack", extratags=extra)
    return buf.getvalue()


def mask_bytes() -> bytes:
    buf = io.BytesIO()
    tifffile.imwrite(buf, np.array([[0, 1], [1, 0]], dtype=np.int16))
    return buf.getvalue()


def make_archive(folder: Path) -> Path:
    folder.mkdir(parents=True)
    path = folder / "hls_burn_scars.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name, data in ((f"training/{NAME}_merged.tif", chip_data()),
                           (f"training/{NAME}.mask.tif", mask_bytes()),
                           (f"validation/{NAME}_merged.tif", chip_data())):  # fmt: skip
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def test_survey_copies_one_chip_and_its_mask_and_leaves_the_archive(tmp_path: Path) -> None:
    archive = make_archive(tmp_path / "a")
    before = archive.stat().st_size
    found = survey(archive, tmp_path / "a" / "sample")
    assert found.members == 3 and found.suffix_counts == {"_merged.tif": 2, ".mask.tif": 1}
    assert found.splits == {"training": 2, "validation": 1} and found.sample_mask is not None
    assert sorted(p.name for p in (tmp_path / "a" / "sample").iterdir()) == [
        f"{NAME}.mask.tif", f"{NAME}_merged.tif",
    ]  # fmt: skip
    assert archive.stat().st_size == before


def test_probe_reports_bands_dtype_crs_nodata_and_mask_values(tmp_path: Path) -> None:
    survey(make_archive(tmp_path / "a"), tmp_path / "s")
    chip = probe(tmp_path / "s" / f"{NAME}_merged.tif")
    assert (chip.band_count, chip.dtype, chip.nodata, chip.nodata_pixels) == (6, "float32", "0", 1)
    assert chip.crs_epsg is None and chip.crs_name == "UTM Zone 14, Northern Hemisphere"
    assert chip.band_names_in_tags == () and chip.origin_xy == (552840.0, 3661530.0)
    assert probe(tmp_path / "s" / f"{NAME}.mask.tif").mask_values == (0, 1)


def test_an_archive_with_no_chip_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "e.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        tar.addfile(tarfile.TarInfo("readme.txt"), io.BytesIO(b""))
    with pytest.raises(ValueError, match="no chip"):
        survey(path, tmp_path / "s")


def test_utm_inverse_matches_known_points() -> None:
    assert utm_to_lonlat(500000, 0, 31) == pytest.approx((3.0, 0.0))
    lon, lat = utm_to_lonlat(552840, 3661530, 14)
    assert (round(lon, 2), round(lat, 2)) == (-98.43, 33.09)
    south = utm_to_lonlat(500000, 10_000_000 - 221_000, 49, north=False)
    assert south[1] == pytest.approx(-2.0, abs=0.01)


def request(**img: object) -> SegmentationRequestV1:
    imagery = Imagery(
        bands=gates.HLS_BANDS, crs="UTM Zone 14", resolution_m=30.0, coverage_fraction=1.0
    ).model_copy(update=img)
    return SegmentationRequestV1(
        request_id="r", question="Map burn scars.", aoi=AOI,
        masks=ReferenceMasks(present=True, source="annotators"), imagery=imagery,
        weights=Weights(asset_id="w", local_state="verified", permission="covered_signed"),
        resources=Resources(
            free_disk_bytes=10**11, needed_bytes=10**9, ram_bytes=16 * 10**9, device="mps"
        ),
    )  # fmt: skip


def test_the_gate_checks_footprint_and_band_order_evidence() -> None:
    far = BoundingBox(min_lon=-98.4, min_lat=33.0, max_lon=-98.3, max_lat=33.1)
    out = gate(request(footprint=far))
    assert any("outside the task area" in r.detail for r in out.refusals)
    assert gate(request(footprint=AOI)).outcome == "authorized"
    unnamed = gate(request(band_order_source="none"))
    assert any("band order" in r.detail for r in unnamed.refusals)
    documented = gate(request(band_order_source="documentation"))
    assert documented.outcome == "authorized" and "dataset card" in documented.notes[0]


def test_measure_gives_two_verdicts_from_real_facts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "assets" / "hls-burn-scars-1864285e"
    make_archive(folder)
    prov = tmp_path / "assets" / "prithvi-burnscars-a3f2c410"
    prov.mkdir()
    (prov / "provenance.json").write_text(json.dumps({"authority": "chat"}), encoding="utf-8")
    out = tmp_path / "s4.json"
    assert main(["--assets", str(tmp_path / "assets"), "--out", str(out)]) == 0
    result = measure(tmp_path / "assets")
    chips, kalimantan = result["verdicts"]["s4-chips"], result["verdicts"]["s4-kalimantan"]  # type: ignore[index]
    assert len(chips["refusals"]) == 1
    assert "chat_only_unsigned" in chips["refusals"][0]["detail"]
    assert any("outside the task area" in r["detail"] for r in kalimantan["refusals"])
    assert "s4-chips request_resources" in capsys.readouterr().out
