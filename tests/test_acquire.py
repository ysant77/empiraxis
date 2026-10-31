"""Tests for approval-gated acquisition and for the pinned Kalimantan data."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, tzinfo
from pathlib import Path
from typing import Any, Self

import httpx
import pytest

from earthlab.acquire import firms
from earthlab.acquire.gate import (
    ApprovalRefused,
    CapExceeded,
    authorize,
    load_approvals,
    write_capped,
)
from earthlab.acquire.run import acquire_firms
from earthlab.cases.loader import load_case
from earthlab.cases.models import ApprovalAction, BoundingBox

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "config" / "cases" / "kalimantan-2015-burned-area.yaml"
APPROVALS = load_approvals(ROOT / "config" / "approvals")
DATA = ROOT / "data" / "kalimantan-2015"
BOX = BoundingBox(min_lon=113.8, min_lat=-3.2, max_lon=114.8, max_lat=-2.0)
INSIDE = datetime.fromisoformat("2026-10-28T00:00:00+00:00")
KEY = "SECRETKEY123"
MCD = "mcd64a1-061-kalimantan-2015"
FIRMS_ASSET = "firms-modis-sp-kalimantan-2015"


def test_recorded_approvals_cover_exactly_what_was_approved() -> None:
    case_id = "kalimantan-2015-burned-area"
    ok = authorize(
        APPROVALS,
        ApprovalAction.DOWNLOAD,
        case_id,
        asset_id=MCD,
        request_bytes=1_000_000,
        at=INSIDE,
    )
    assert ok.approval_id == "kal-2015-download-mcd64a1"
    authorize(APPROVALS, ApprovalAction.CONFIRM_STUDY_AREA, case_id, at=INSIDE)
    refusals: list[dict[str, Any]] = [
        {"asset_id": MCD, "request_bytes": 20_000_000, "at": INSIDE},  # over the cap
        {"asset_id": "landsat-scenes", "request_bytes": 1, "at": INSIDE},  # not approved
        {
            "asset_id": MCD,
            "request_bytes": 1,
            "at": datetime.fromisoformat("2026-11-02T00:00:00+00:00"),
        },
    ]
    for kwargs in refusals:
        with pytest.raises(ApprovalRefused):
            authorize(APPROVALS, ApprovalAction.DOWNLOAD, case_id, **kwargs)
    with pytest.raises(ApprovalRefused, match="no approval recorded"):
        authorize(
            APPROVALS,
            ApprovalAction.DOWNLOAD,
            "uttarakhand-2024-burned-area",
            asset_id=MCD,
            request_bytes=1,
            at=INSIDE,
        )


def test_capped_writer_deletes_a_stream_over_the_cap(tmp_path: Path) -> None:
    sha, size = write_capped([b"abc", b"def"], tmp_path / "ok.bin", 6)
    assert size == 6 and sha == hashlib.sha256(b"abcdef").hexdigest()
    with pytest.raises(CapExceeded):
        write_capped([b"abc", b"defg"], tmp_path / "big.bin", 6)
    assert not list(tmp_path.glob("big.bin*"))


def test_firms_chunks_urls_and_redaction() -> None:
    parts = firms.chunks(date(2015, 9, 1), date(2015, 11, 1))
    assert len(parts) == 13 and all(1 <= n <= firms.MAX_DAYS for _, n in parts)
    assert parts[0] == (date(2015, 9, 1), 5) and sum(n for _, n in parts) == 61
    url = firms.request_url(KEY, "MODIS_SP", BOX, date(2015, 9, 1), 5)
    assert url.endswith(f"/{KEY}/MODIS_SP/113.8,-3.2,114.8,-2.0/5/2015-09-01")
    assert KEY not in firms.redact(f"error at {url}", KEY)
    joined = b"".join(firms.joined_csv(["latitude,x\n1,2\n", "latitude,x\n3,4\n"]))
    assert joined == b"latitude,x\n1,2\n3,4\n"
    with pytest.raises(ValueError, match="different headers"):
        list(firms.joined_csv(["latitude,x\n1,2\n", "latitude,y\n3,4\n"]))


def _transport(reply: str, status: int = 200) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, text=reply))


class _InsideApprovalWindow(datetime):
    """The real approvals expired by design; these tests check the download path."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        return cls(2026, 10, 30, tzinfo=tz)


def test_firms_errors_never_show_the_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("earthlab.acquire.gate.datetime", _InsideApprovalWindow)
    case_file = load_case(CASE, ROOT)
    monkeypatch.setenv("FIRMS_API_KEY", KEY)
    bad = lambda: httpx.Client(transport=_transport(f"Invalid MAP_KEY {KEY}", 400))  # noqa: E731
    with pytest.raises(RuntimeError) as err:
        acquire_firms(case_file, FIRMS_ASSET, APPROVALS, tmp_path, client_factory=bad)
    assert KEY not in str(err.value) and "<MAP_KEY>" in str(err.value)
    monkeypatch.delenv("FIRMS_API_KEY")
    with pytest.raises(RuntimeError, match="FIRMS_API_KEY is not set"):
        acquire_firms(case_file, FIRMS_ASSET, APPROVALS, tmp_path, client_factory=bad)


def test_firms_acquisition_writes_a_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("earthlab.acquire.gate.datetime", _InsideApprovalWindow)
    monkeypatch.setenv("FIRMS_API_KEY", KEY)
    good = lambda: httpx.Client(transport=_transport("latitude,longitude\n-3.0,114.0\n"))  # noqa: E731
    manifest = acquire_firms(
        load_case(CASE, ROOT), FIRMS_ASSET, APPROVALS, tmp_path, client_factory=good
    )
    entry = manifest["files"][0]
    assert entry["rows"] == 13 and entry["requests"] == 13
    assert manifest["approval_id"] == "kal-2015-download-firms"
    assert KEY not in json.dumps(manifest)


def _manifest(asset_id: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((DATA / f"{asset_id}.manifest.json").read_text("utf-8"))
    return loaded


def test_pinned_files_match_their_manifests_and_the_case() -> None:
    case_file = load_case(CASE, ROOT)
    for asset_id in (MCD, FIRMS_ASSET):
        manifest = _manifest(asset_id)
        for entry in manifest["files"]:
            body = (DATA / entry["file"]).read_bytes()
            assert (
                hashlib.sha256(body).hexdigest() == entry["sha256"] and len(body) == entry["bytes"]
            )
        raw = (DATA / f"{asset_id}.manifest.json").read_bytes()
        assert case_file.assets[asset_id].sha256 == hashlib.sha256(raw).hexdigest()
        assert manifest["approval_id"] in {a.approval_id for a in APPROVALS}
        assert manifest["total_bytes"] <= 10_000_000


def test_pinned_firms_rows_lie_inside_the_box_and_period() -> None:
    entry = _manifest(FIRMS_ASSET)["files"][0]
    with (DATA / entry["file"]).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == entry["rows"]
    assert all(BOX.min_lat <= float(r["latitude"]) <= BOX.max_lat for r in rows)
    assert all(BOX.min_lon <= float(r["longitude"]) <= BOX.max_lon for r in rows)
    assert all("2015-09-01" <= r["acq_date"] < "2015-11-01" for r in rows)


def test_mcd64a1_manifest_records_the_reference_and_fill_meaning() -> None:
    files = _manifest(MCD)["files"]
    assert [f["month"] for f in files] == ["2015-09", "2015-10"]
    for f in files:
        ref = f["reference"]
        assert f["fill_value"] == -1 and "unburned or unmapped" in f["fill_meaning"]
        assert (
            f["grid"]["crs"] == "SR-ORG:6974"
            and ref["burned_valid_pixels"] <= ref["valid_land_pixels"]
        )
        assert ref["valid_land_pixels"] <= ref["land_pixels"] <= ref["pixels_in_box"]
