"""A read-only audit of the data on this machine. It downloads nothing.

Each local product gets a `DatasetSuitabilityV1` profile built from its manifest. The audit
checks every hash against its manifest. A product that has no manifest, or no hash, is
reported as unverified. Products that are not on the disk are reported as not acquired.
"""

from __future__ import annotations

import argparse
import csv
import json
import tarfile
from pathlib import Path
from typing import Any

from earthlab.cases.models import BoundingBox
from earthlab.contracts import Strict
from earthlab.data.nea_pm25 import load_pm25
from earthlab.data.snapshot import SourceMismatchError, open_snapshot
from earthlab.digest import file_digest
from earthlab.harness.audit_catalogue import NOT_ACQUIRED, unacquired_profile
from earthlab.harness.suitability import (
    DatasetSuitabilityV1,
    VariableSpec,
    parse_timestamp,
)
from earthlab.haze.cli import verify_manifest

SINGAPORE = BoundingBox(min_lon=103.6, min_lat=1.15, max_lon=104.1, max_lat=1.5)
NEA_URL = "https://data.gov.sg/datasets/d_6c0d5fc34838b12472475fdb73c0af29/view"
LISTING_LIMIT = 12
ERA5_SL_VARS = (
    VariableSpec(name="10m_u_wind", unit="m s-1", accumulation="instant"),
    VariableSpec(name="10m_v_wind", unit="m s-1", accumulation="instant"),
    VariableSpec(name="total_precipitation", unit="m", accumulation="accumulated"),
    VariableSpec(name="boundary_layer_height", unit="m", accumulation="instant"),
)
ERA5_PL_VARS = (
    VariableSpec(name="u_wind_850hpa", unit="m s-1", accumulation="instant"),
    VariableSpec(name="v_wind_850hpa", unit="m s-1", accumulation="instant"),
)


class AuditEntry(Strict):
    profile: DatasetSuitabilityV1
    checks: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    unverifiable: tuple[str, ...] = ()


class AuditReportV1(Strict):
    schema_version: str = "1"
    entries: tuple[AuditEntry, ...]
    stray_files: tuple[str, ...] = ()


def _box(raw: dict[str, float]) -> BoundingBox:
    return BoundingBox(
        min_lon=raw["min_lon"], min_lat=raw["min_lat"], max_lon=raw["max_lon"],
        max_lat=raw["max_lat"],
    )  # fmt: skip


def _manifest_profile(
    manifest: Path, approvals: Path, variables: tuple[VariableSpec, ...], **fixed: Any
) -> AuditEntry:
    """Common fields from a hash-checked manifest of a downloaded product."""
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    problems = verify_manifest(manifest, approvals)
    hashes = ",".join(entry["sha256"][:12] for entry in raw["files"])
    state = "verified" if not problems else "hash_mismatch"
    cover = raw["coverage"]
    profile = DatasetSuitabilityV1(
        dataset_id=raw["asset_id"], revision=str(raw.get("version", "")),
        source_url=raw["source_url"], variables=variables, crs=raw.get("crs"),
        area=_box(raw["extent"]), first_time=parse_timestamp(cover["start"]),
        last_time=parse_timestamp(cover["end"]), license=raw["licence"],
        bytes_estimate=raw["total_bytes"], local_state=state, local_path=str(manifest.parent),
        local_sha256=raw["files"][0]["sha256"], permission="covered_signed", **fixed,
    )  # fmt: skip
    checks = (f"{len(raw['files'])} file hashes, size and byte cap checked: {hashes}",)
    bad = tuple(problems)
    return AuditEntry(profile=profile, checks=checks, problems=bad)


def audit_nea(data_dir: Path) -> AuditEntry:
    try:
        snapshot, path = open_snapshot(data_dir)
    except SourceMismatchError as exc:
        return AuditEntry(profile=_nea_profile("hash_mismatch", None, None), problems=(str(exc),))
    dataset = load_pm25(path, snapshot)
    first, last = dataset.rows[0].time, dataset.rows[-1].time
    counts = dataset.issue_counts()
    checks = (
        f"sha256 matches manifest; {len(dataset.rows)} hourly rows after repair",
        f"parse issues by kind: {counts}",
    )
    return AuditEntry(profile=_nea_profile("verified", first, last, snapshot.sha256), checks=checks)


def _nea_profile(state: str, first: Any, last: Any, sha: str | None = None) -> DatasetSuitabilityV1:
    return DatasetSuitabilityV1(
        dataset_id="nea-historical-1hr-pm25", revision="source updated 2026-10-20",
        source_url=NEA_URL, variables=(VariableSpec(name="pm25", unit="ug/m3"),),
        crs=None, grid="five NEA regions", area=SINGAPORE, first_time=first, last_time=last,
        cadence_hours=1.0, spatial_support="region", event_time="unknown", valid_time="unknown",
        data_kind="observation", availability="unknown", license="Singapore Open Data Licence v1.0",
        local_state=state, local_sha256=sha, permission="not_required",
        allowed_evidence=("historical_research", "hindsight_diagnostic", "transport_plausibility"),
        notes=("hour label convention unknown", "no available-at field: no issue-time claim"),
    )  # fmt: skip


def audit_era5(manifest: Path, approvals: Path) -> AuditEntry:
    surface = "sl" in manifest.name
    entry = _manifest_profile(
        manifest, approvals, ERA5_SL_VARS if surface else ERA5_PL_VARS,
        grid="0.25 degree", cadence_hours=1.0, spatial_support="grid_cell",
        event_time="instant", valid_time="instant",
        data_kind="reanalysis", availability="not_applicable", missing_fraction=0.0,
        allowed_evidence=("hindsight_diagnostic", "transport_plausibility"),
        notes=("perfect-weather hindcast only", "tp is metres of water in the hour ending"),
    )  # fmt: skip
    return entry


def audit_firms(manifest: Path, approvals: Path) -> AuditEntry:
    entry = _manifest_profile(
        manifest, approvals, (VariableSpec(name="thermal_anomaly", unit="detection"),),
        spatial_support="point", event_time="instant", valid_time="instant",
        data_kind="observation", availability="unknown",
        quality_masks=("confidence",),
        allowed_evidence=("transport_plausibility", "historical_research"),
        notes=("overpass only; cloud and smoke hide fires; zero is not none",),
    )  # fmt: skip
    path = manifest.parent / json.loads(manifest.read_text("utf-8"))["files"][0]["file"]
    types: dict[str, int] = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            types[row["type"]] = types.get(row["type"], 0) + 1
    note = f"rows by FIRMS type flag (0 vegetation, 2 other static land, 3 offshore): {types}"
    return entry.model_copy(update={"checks": (*entry.checks, note)})


def audit_mcd64a1(manifest: Path, approvals: Path) -> AuditEntry:
    return _manifest_profile(
        manifest, approvals, (VariableSpec(name="burn_date", unit="day of year"),),
        grid="463 m sinusoidal", spatial_support="grid_cell", event_time="interval",
        valid_time="interval", data_kind="derived_product", availability="unknown",
        quality_masks=("qa", "valid_fraction"), allowed_evidence=("historical_research",),
        notes=("a mapped burn date, not independent pixel ground truth",),
    )  # fmt: skip


def _listing(archive: Path) -> list[str]:
    names: list[str] = []
    with tarfile.open(archive, "r|gz") as tar:
        for member in tar:
            names.append(member.name)
            if len(names) >= LISTING_LIMIT:
                break
    return names


def audit_asset(folder: Path, kind: str) -> AuditEntry:
    """A pinned asset with a provenance.json. Chat approval is not a signed record."""
    prov = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    name = "Prithvi_EO_V2_300M_BurnScars.pt" if kind == "weights" else "hls_burn_scars.tar.gz"
    path = folder / name
    actual = file_digest(path)
    problems = [] if actual == prov["sha256"] else ("sha256 differs from provenance.json",)
    if path.stat().st_size != prov["bytes"]:
        problems = (*problems, "size differs from provenance.json")
    checks = [f"sha256 {actual[:12]} against provenance.json", f"authority: {prov['authority']}"]
    unverifiable = ["no signed ResourceApprovalV1 exists; the approval is a chat statement"]
    if kind == "chips":
        checks.append(f"first archive members (listing only): {_listing(path)}")
        unverifiable += ["band order, CRS and cloud masks inside the chips were not read"]
    else:
        unverifiable += ["the .pt file was not loaded; its contents were not inspected"]
    profile = unacquired_profile(kind, prov, "verified" if not problems else "hash_mismatch")
    profile = profile.model_copy(update={"local_path": str(path), "local_sha256": actual})
    return AuditEntry(
        profile=profile, checks=tuple(checks), problems=tuple(problems),
        unverifiable=tuple(unverifiable),
    )  # fmt: skip


def stray_files(roots: list[Path]) -> tuple[str, ...]:
    """Files whose names suggest a product that the audit reports as not acquired."""
    marks = ("MCD19A2", "SPL3SMP", "SPL4SMGP", "EMITL2", "cams")
    found = [
        str(p) for root in roots if root.is_dir()
        for p in root.rglob("*") if any(m.lower() in p.name.lower() for m in marks)
    ]  # fmt: skip
    return tuple(sorted(found))


def run_audit(repo: Path, haze_runs: Path, assets: Path) -> AuditReportV1:
    approvals = repo / "config" / "approvals"
    era5 = sorted((haze_runs / "era5").glob("*.manifest.json"))
    firms = sorted((haze_runs / "firms").glob("*/*.manifest.json"))
    entries = [audit_nea(repo / "data" / "nea")]
    entries += [audit_era5(m, approvals) for m in era5]
    entries += [audit_firms(m, approvals) for m in firms]
    entries.append(audit_mcd64a1(next((repo / "data/kalimantan-2015").glob("mcd64a1*.json")),
                                 approvals))  # fmt: skip
    entries += [audit_asset(assets / "prithvi-burnscars-a3f2c410", "weights")]
    entries += [audit_asset(assets / "hls-burn-scars-1864285e", "chips")]
    strays = stray_files([repo / "data", haze_runs, assets])
    entries += [AuditEntry(profile=unacquired_profile(key, {}, "not_acquired"))
                for key in NOT_ACQUIRED]  # fmt: skip
    return AuditReportV1(entries=tuple(entries), stray_files=strays)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit local data. Downloads nothing.")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--haze-runs", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_audit(args.repo, args.haze_runs, args.assets)
    args.out.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    for entry in report.entries:
        p = entry.profile
        print(
            f"{p.dataset_id:44} {p.local_state:14} {p.permission:20} {len(entry.problems)} problems"
        )
    return 1 if any(e.problems for e in report.entries) else 0


if __name__ == "__main__":
    raise SystemExit(main())
