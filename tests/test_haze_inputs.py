"""ERA5 corridor extract, FIRMS detections and the haze CLI, on synthetic files only."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from haze_synthetic import episode, met_series, steady, write_nea

from earthlab.cases.models import BoundingBox
from earthlab.data.snapshot import SourceMismatchError
from earthlab.haze import cli
from earthlab.haze.evidence import SourceRef
from earthlab.haze.fires import count_in_window, read_manifest
from earthlab.haze.geometry import H1_SOURCE_BOXES, corridor
from earthlab.haze.met import (
    GridField,
    box_mean,
    corridor_series,
    verified_files,
    with_surface_precip,
)
from earthlab.haze.sector import MetSeries

T0 = datetime(2015, 9, 20, tzinfo=UTC)
LATS = np.array([2.0, 1.0, 0.0, -1.0])
LONS = np.array([100.0, 101.0, 102.0, 103.0, 104.0])


def _field(name: str, value: float, hour: int = 0, level: int | None = None) -> GridField:
    values = np.full((LATS.size, LONS.size), value)
    values[0, 0] = np.nan  # one missing cell is skipped, not read as zero
    return GridField(name, level, T0 + timedelta(hours=hour), LATS, LONS, values)


def test_box_mean_uses_cell_centres_inside_the_box() -> None:
    field = _field("10u", 2.0)
    field.values[1, 1] = 6.0
    box = BoundingBox(min_lon=99.5, min_lat=0.5, max_lon=102.5, max_lat=2.5)
    # Six cells inside; the NaN cell is skipped, so five values remain.
    assert box_mean(field, box) == pytest.approx((6.0 + 4 * 2.0) / 5)
    outside = BoundingBox(min_lon=110.0, min_lat=0.0, max_lon=111.0, max_lat=1.0)
    assert box_mean(field, outside) is None


def test_corridor_series_joins_fields_by_hour_and_converts_rain() -> None:
    fields = [
        _field("10u", 3.0, 1),
        _field("10v", -4.0, 1),
        _field("tp", 0.002, 1),
        _field("10u", 1.0, 0),
        _field("blh", 900.0, 0),
        _field("u", 9.0, 0, level=850),
    ]
    box = BoundingBox(min_lon=99.0, min_lat=-2.0, max_lon=105.0, max_lat=3.0)
    ref = SourceRef(dataset_id="synthetic-era5", file="x.grib", sha256="1" * 64)
    series = corridor_series(fields, box, "box-a", "10m", (ref,))
    assert [h.time for h in series.hours] == [T0, T0 + timedelta(hours=1)]
    assert (series.hours[0].u_ms, series.hours[0].v_ms) == (1.0, None)
    assert series.hours[1].precip_mm == pytest.approx(2.0)
    upper = corridor_series(fields, box, "box-a", "850hPa", (ref,))
    assert [(h.u_ms, h.v_ms) for h in upper.hours] == [(9.0, None)]


def _pinned(folder: Path, asset_id: str, name: str, data: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    manifest = {
        "asset_id": asset_id,
        "files": [{"file": name, "sha256": hashlib.sha256(data).hexdigest()}],
    }
    path = folder / f"{asset_id}.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_manifest_hash_mismatch_is_refused(tmp_path: Path) -> None:
    manifest = _pinned(tmp_path, "synthetic-era5", "a.grib", b"GRIB")
    assert verified_files(manifest)[0][1].file == "a.grib"
    (tmp_path / "a.grib").write_bytes(b"GRIX")
    with pytest.raises(SourceMismatchError):
        verified_files(manifest)


def test_firms_reader_parses_utc_overpass_and_counts_in_box(tmp_path: Path) -> None:
    lat, lon = H1_SOURCE_BOXES[1].centre
    rows = "latitude,longitude,acq_date,acq_time,confidence\n"
    rows += f"{lat},{lon},2015-09-19,5,80\n"  # acq_time with leading zeros dropped
    rows += f"{lat},{lon},2015-09-19,1830,20\n"  # below the confidence floor
    rows += "0.0,90.0,2015-09-19,0300,90\n"  # outside the box
    manifest = _pinned(tmp_path, "synthetic-firms-box-b", "f.csv", rows.encode())
    detections, refs = read_manifest(manifest)
    assert detections[0].time == datetime(2015, 9, 19, 0, 5, tzinfo=UTC)
    assert detections[1].time == datetime(2015, 9, 19, 18, 30, tzinfo=UTC)
    count = count_in_window(detections, H1_SOURCE_BOXES[1], T0 - timedelta(days=2), T0, 30)
    assert count == 1 and refs[0].dataset_id == "synthetic-firms-box-b"


class FakeDecoder:
    def fields(self, path: Path) -> Iterator[GridField]:
        lats, lons = np.arange(4.0, -6.25, -0.25), np.arange(95.0, 118.25, 0.25)
        for name, value in (("10u", 2.0), ("10v", 3.0), ("tp", 0.0)):
            yield GridField(name, None, T0, lats, lons, np.full((lats.size, lons.size), value))


def test_extract_cli_builds_every_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _pinned(tmp_path, "synthetic-era5", "a.grib", b"GRIB")
    series = cli.build_extract(manifest, "10m", FakeDecoder())
    assert [s.box_id for s in series] == ["box-a", "box-b", "box-c"]
    assert series[2].hours[0].u_ms == 2.0 and series[2].sources[0].file == "a.grib"
    assert corridor(H1_SOURCE_BOXES[2]).max_lon > 111
    monkeypatch.setattr(cli, "load_decoder", FakeDecoder)
    out = tmp_path / "extract.json"
    assert cli.cmd_extract(argparse.Namespace(manifest=manifest, level="10m", out=out)) == 0
    assert set(cli.read_extract(out)) == {"box-a", "box-b", "box-c"}


def _extract(path: Path, series: dict[str, MetSeries]) -> Path:
    payload = {"series": [s.model_dump(mode="json") for s in series.values()]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_h1_cli_runs_full_path_and_fallback(tmp_path: Path) -> None:
    nea = write_nea(tmp_path / "nea", episode(datetime(2015, 9, 24, 20, tzinfo=UTC), 6, 140.0))
    fallback_out = tmp_path / "fallback.json"
    cli.cmd_h1(argparse.Namespace(nea=nea, met=[], firms=[], out=fallback_out))
    fallback = json.loads(fallback_out.read_text())
    assert fallback["report"]["provenance"]["evidence_class"] == "observation"
    extract = _extract(tmp_path / "extract.json", met_series(steady(8.0, rain=3.0)))
    upper = _extract(tmp_path / "upper.json", met_series(steady(8.0), level="850hPa"))
    lat, lon = H1_SOURCE_BOXES[0].centre
    firms = _pinned(
        tmp_path / "firms",
        "synthetic-firms-box-a",
        "f.csv",
        f"latitude,longitude,acq_date,acq_time,confidence\n{lat},{lon},2015-09-23,0300,70\n".encode(),
    )
    out = tmp_path / "h1.json"
    args = argparse.Namespace(nea=nea, met=[upper, extract], firms=[firms], out=out)
    assert cli.cmd_h1(args) == 0
    levels = json.loads(out.read_text())["levels"]
    assert sorted(levels) == ["10m", "850hPa"]
    for document in levels.values():
        report = document["report"]
        assert report["provenance"]["evidence_class"] == "transport_plausibility"
        assert document["time_sensitive_boxes"] == [] and len(document["digest"]) == 64
        # Surface rain of 3 mm/h reaches the 850 hPa check too, so nothing is consistent.
        statuses = {b["status"] for o in report["onsets"] for b in o["boxes"]}
        assert statuses == {"inconclusive"}
    with pytest.raises(ValueError, match="needs the 10m extract"):
        cli.met_by_level([upper])
    with pytest.raises(ValueError, match="two extracts"):
        cli.met_by_level([extract, extract])
    h0_out = tmp_path / "h0.json"
    assert cli.cmd_h0(argparse.Namespace(nea=nea, out=h0_out)) == 0
    with pytest.raises(ValueError, match="matches no H1 source box"):
        cli.read_fires(
            [_pinned(tmp_path / "other", "synthetic-firms-box-z", "g.csv", b"latitude\n")]
        )


def test_verify_checks_hash_size_and_cap(tmp_path: Path) -> None:
    data = b"latitude,longitude\n0.0,101.0\n"
    (tmp_path / "f.csv").write_bytes(data)
    manifest = {
        "asset_id": "firms-modis-sp-haze-2015-box-a",
        "approval_id": "haze-2015-h1-download-firms-box-a",
        "files": [
            {"file": "f.csv", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        ],
        "total_bytes": len(data),
    }
    path = tmp_path / "m.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    approvals = Path(__file__).resolve().parents[1] / "config" / "approvals"
    assert cli.verify_manifest(path, approvals) == []
    assert cli.cmd_verify(argparse.Namespace(manifest=path, approvals=approvals)) == 0
    (tmp_path / "f.csv").write_bytes(data + b"1.0,102.0\n")
    path.write_text(json.dumps({**manifest, "total_bytes": 7_000_000}), encoding="utf-8")
    problems = cli.verify_manifest(path, approvals)
    assert any("sha256" in p for p in problems) and any("size" in p for p in problems)
    assert any("cap" in p for p in problems)
    assert cli.cmd_verify(argparse.Namespace(manifest=path, approvals=approvals)) == 1
    (tmp_path / "f.csv").unlink()
    path.write_text(json.dumps({**manifest, "approval_id": "unknown"}), encoding="utf-8")
    assert cli.verify_manifest(path, approvals) == [
        "f.csv: missing",
        "approval unknown has no recorded byte cap",
    ]


def test_surface_precip_joins_by_hour_and_refuses_other_boxes() -> None:
    surface = met_series(steady(5.0, rain=2.0))
    upper = met_series(steady(9.0), level="850hPa")
    joined = with_surface_precip(upper["box-a"], surface["box-a"])
    assert joined.level == "850hPa" and {h.precip_mm for h in joined.hours} == {2.0}
    assert joined.hours[0].u_ms == upper["box-a"].hours[0].u_ms
    with pytest.raises(ValueError, match="box mismatch"):
        with_surface_precip(upper["box-a"], surface["box-b"])
