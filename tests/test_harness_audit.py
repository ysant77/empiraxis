"""The local data audit: hash checks, honest approval labels and products not acquired."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from haze_synthetic import write_nea

from earthlab.harness.audit import (
    audit_asset,
    audit_firms,
    audit_mcd64a1,
    main,
    stray_files,
)
from earthlab.harness.audit_catalogue import NOT_ACQUIRED, unacquired_profile

CSV = (
    "latitude,longitude,acq_date,acq_time,confidence,type\n"
    "-3.0,104.0,2015-09-01,305,80,0\n-3.1,104.1,2015-09-01,305,70,2\n"
)
APPROVAL = """\
approvals:
  - approval_id: test-download
    case_id: test-case
    action: download
    approved: true
    approver: owner
    decided_at_utc: "2026-10-29T08:00:00Z"
    expires_at_utc: "2026-10-31T08:00:00Z"
    asset_ids: [firms-test]
    max_bytes: 10000
"""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_manifest(folder: Path, data: bytes, name: str, **extra: object) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    raw = {
        "asset_id": "firms-test", "version": "6.1", "source_url": "https://example.org/firms",
        "licence": "open", "crs": "EPSG:4326", "approval_id": "test-download",
        "extent": {"min_lon": 102.5, "min_lat": -4.5, "max_lon": 106.5, "max_lat": -1.0},
        "coverage": {"start": "2015-08-25T00:00:00Z", "end": "2015-11-01T00:00:00Z"},
        "files": [{"file": name, "sha256": sha(data), "bytes": len(data)}],
        "total_bytes": len(data),
    } | extra  # fmt: skip
    path = folder / "x.manifest.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


@pytest.fixture
def approvals(tmp_path: Path) -> Path:
    folder = tmp_path / "approvals"
    folder.mkdir()
    (folder / "a.yaml").write_text(APPROVAL, encoding="utf-8")
    return folder


def test_firms_hashes_pass_and_static_flags_are_counted(tmp_path: Path, approvals: Path) -> None:
    manifest = make_manifest(tmp_path / "firms", CSV.encode(), "f.csv")
    entry = audit_firms(manifest, approvals)
    assert entry.profile.local_state == "verified" and not entry.problems
    assert "'0': 1" in entry.checks[-1] and "'2': 1" in entry.checks[-1]
    assert entry.profile.data_kind == "observation" and entry.profile.availability == "unknown"


def test_a_changed_file_is_reported_as_a_hash_mismatch(tmp_path: Path, approvals: Path) -> None:
    manifest = make_manifest(tmp_path / "firms", CSV.encode(), "f.csv")
    (manifest.parent / "f.csv").write_text(CSV + "-3.2,104.2,2015-09-02,305,60,0\n")
    entry = audit_firms(manifest, approvals)
    assert entry.profile.local_state == "hash_mismatch"
    assert any("sha256 differs" in p for p in entry.problems)


def test_mcd64a1_is_a_derived_product_not_ground_truth(tmp_path: Path, approvals: Path) -> None:
    make_manifest(tmp_path / "kal", b"tif", "mcd64a1_2015_09.tif")
    manifest = next((tmp_path / "kal").glob("*.json"))
    entry = audit_mcd64a1(manifest, approvals)
    assert entry.profile.data_kind == "derived_product"
    assert any("not independent" in n for n in entry.profile.notes)


def make_asset(folder: Path, name: str, data: bytes, **change: object) -> None:
    folder.mkdir(parents=True)
    (folder / name).write_bytes(data)
    prov = {
        "asset": "x", "url": "https://example.org/x", "revision": "abcdef123456",
        "bytes": len(data), "sha256": sha(data), "license_terms": "Apache-2.0",
        "authority": "owner approval in chat, 2026-11-01; no signed ResourceApprovalV1 exists",
    } | change  # fmt: skip
    (folder / "provenance.json").write_text(json.dumps(prov), encoding="utf-8")


def test_a_chat_approved_asset_is_reported_as_unsigned(tmp_path: Path) -> None:
    make_asset(tmp_path / "w", "Prithvi_EO_V2_300M_BurnScars.pt", b"not real weights")
    entry = audit_asset(tmp_path / "w", "weights")
    assert entry.profile.local_state == "verified" and not entry.problems
    assert entry.profile.permission == "chat_only_unsigned"
    assert any("no signed ResourceApprovalV1" in u for u in entry.unverifiable)
    assert any("not loaded" in u for u in entry.unverifiable)
    assert any("owner approval in chat" in c for c in entry.checks)


def test_chips_are_listed_but_not_extracted(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name in ("training/a.tif", "training/b.tif"):
            info = tarfile.TarInfo(name)
            info.size = 3
            tar.addfile(info, io.BytesIO(b"abc"))
    make_asset(tmp_path / "c", "hls_burn_scars.tar.gz", buffer.getvalue())
    entry = audit_asset(tmp_path / "c", "chips")
    assert any("training/a.tif" in c for c in entry.checks)
    assert not list((tmp_path / "c").glob("training"))
    assert any("band order" in u for u in entry.unverifiable)
    assert entry.profile.optical and "multispectral" in entry.profile.notes[-1]


def test_a_changed_asset_fails_the_hash_check(tmp_path: Path) -> None:
    make_asset(tmp_path / "w", "Prithvi_EO_V2_300M_BurnScars.pt", b"abc", sha256="0" * 64)
    entry = audit_asset(tmp_path / "w", "weights")
    assert entry.profile.local_state == "hash_mismatch" and entry.problems


def test_products_not_on_disk_are_reported_not_acquired() -> None:
    assert set(NOT_ACQUIRED) == {
        "maiac-mcd19a2", "smap-spl3smp-e", "emit-l2a-rfl", "cams-archived-forecast",
    }  # fmt: skip
    for key in NOT_ACQUIRED:
        p = unacquired_profile(key, {}, "not_acquired")
        assert p.local_state == "not_acquired" and p.permission == "needs_approval"
        assert p.local_sha256 is None and p.local_path is None
    emit = unacquired_profile("emit-l2a-rfl", {}, "not_acquired")
    assert emit.spatial_support == "swath" and "2022" in emit.notes[0]


def test_stray_files_are_named_not_trusted(tmp_path: Path) -> None:
    (tmp_path / "MCD19A2.A2015250.hdf").write_bytes(b"")
    (tmp_path / "other.txt").write_bytes(b"")
    assert [Path(p).name for p in stray_files([tmp_path, tmp_path / "none"])] == [
        "MCD19A2.A2015250.hdf"
    ]


def test_the_audit_runs_on_a_small_tree_and_writes_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    (repo / "config" / "approvals").mkdir(parents=True)
    (repo / "config" / "approvals" / "a.yaml").write_text(APPROVAL, encoding="utf-8")
    make_manifest(repo / "data" / "kalimantan-2015", b"tif", "mcd64a1_2015_09.tif")
    (repo / "data" / "kalimantan-2015" / "x.manifest.json").rename(
        repo / "data/kalimantan-2015/mcd64a1-x.json"
    )
    runs = tmp_path / "runs"
    make_manifest(runs / "firms" / "box-a", CSV.encode(), "f.csv")
    make_manifest(runs / "era5", b"grib", "era5_sl_2015_09.grib")
    (runs / "era5" / "x.manifest.json").rename(runs / "era5" / "era5-sl-test.manifest.json")
    make_asset(
        tmp_path / "assets" / "prithvi-burnscars-a3f2c410", "Prithvi_EO_V2_300M_BurnScars.pt", b"w"
    )
    make_asset(tmp_path / "assets" / "hls-burn-scars-1864285e", "hls_burn_scars.tar.gz", _tar())
    write_nea(repo / "data" / "nea")
    out = tmp_path / "audit.json"
    args = ["--repo", str(repo), "--haze-runs", str(runs), "--assets", str(tmp_path / "assets")]
    assert main([*args, "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    states = {e["profile"]["dataset_id"]: e["profile"]["local_state"] for e in document["entries"]}
    assert len(document["entries"]) == 10 and states["nea-historical-1hr-pm25"] == "verified"
    assert states["maiac-mcd19a2"] == "not_acquired" and "verified" in capsys.readouterr().out


def _tar() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("training/a.tif")
        tar.addfile(info, io.BytesIO(b""))
    return buffer.getvalue()
