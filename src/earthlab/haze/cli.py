"""Command-line entry points for the haze case: H0, the ERA5 extract and H1 or its fallback.

Every command reads only pinned, hash-checked files and writes one JSON document that
holds the typed report and its digest.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from earthlab.acquire.gate import load_approvals
from earthlab.contracts import SGT, Strict, TimeWindow
from earthlab.data.nea_pm25 import load_pm25
from earthlab.data.snapshot import open_snapshot
from earthlab.digest import file_digest
from earthlab.haze import fires as fires_mod
from earthlab.haze import met as met_mod
from earthlab.haze.base_rate import run_base_rate
from earthlab.haze.evidence import SourceRef, output_digest
from earthlab.haze.fallback import fallback_report
from earthlab.haze.geometry import H1_SOURCE_BOXES, corridor
from earthlab.haze.grib import load_decoder
from earthlab.haze.h0 import H0Report, describe
from earthlab.haze.h1 import run_h1, time_sensitive_boxes
from earthlab.haze.sector import MetSeries
from earthlab.haze.timebase import HourConvention

H1_WINDOW = TimeWindow(
    start=datetime(2015, 9, 1, tzinfo=SGT), end=datetime(2015, 11, 1, tzinfo=SGT)
)


def write_report(report: Strict, out: Path, extra: dict[str, Any] | None = None) -> Path:
    document = {"report": report.model_dump(mode="json"), "digest": output_digest(report)}
    document.update(extra or {})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return out


def load_h0(nea_dir: Path) -> H0Report:
    snapshot, path = open_snapshot(nea_dir)
    return describe(load_pm25(path, snapshot), H1_WINDOW)


def build_extract(
    manifest: Path, level: met_mod.Level, decoder: met_mod.GridDecoder
) -> list[MetSeries]:
    """Corridor-mean series for every source box from one hash-checked ERA5 manifest."""
    files = met_mod.verified_files(manifest)
    fields = [field for path, _ in files for field in decoder.fields(path)]
    refs = tuple(ref for _, ref in files)
    return [
        met_mod.corridor_series(fields, corridor(s), s.box_id, level, refs) for s in H1_SOURCE_BOXES
    ]


def read_extract(path: Path) -> dict[str, MetSeries]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    series = [MetSeries.model_validate(item) for item in raw["series"]]
    return {s.box_id: s for s in series}


def read_fires(
    manifests: list[Path],
) -> tuple[dict[str, list[fires_mod.FireDetection]], tuple[SourceRef, ...]]:
    """Detections per box id; a manifest belongs to the box its asset id ends with."""
    by_box: dict[str, list[fires_mod.FireDetection]] = {}
    refs: list[SourceRef] = []
    # Box order, so the output digest does not depend on the order of the --firms options.
    assets = {m: json.loads(m.read_text(encoding="utf-8"))["asset_id"] for m in manifests}
    for manifest, asset in sorted(assets.items(), key=lambda item: item[1]):
        detections, file_refs = fires_mod.read_manifest(manifest)
        box = next((s.box_id for s in H1_SOURCE_BOXES if asset.endswith(s.box_id)), None)
        if box is None:
            raise ValueError(f"{asset} matches no H1 source box")
        by_box.setdefault(box, []).extend(detections)
        refs += file_refs
    return by_box, tuple(refs)


def cmd_h0(args: argparse.Namespace) -> int:
    report = load_h0(args.nea)
    write_report(report, args.out)
    print(f"H0: {len(report.events)} event periods, {report.event_hours} event hours -> {args.out}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    series = build_extract(args.manifest, args.level, load_decoder())
    payload = {"series": [s.model_dump(mode="json") for s in series]}
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"ERA5 extract ({args.level}) for {len(series)} boxes -> {args.out}")
    return 0


def met_by_level(paths: list[Path]) -> dict[str, dict[str, MetSeries]]:
    """Extracts grouped by level. 850 hPa needs the 10 m extract for path rain."""
    levels: dict[str, dict[str, MetSeries]] = {}
    for path in paths:
        series = read_extract(path)
        level = next(iter(series.values())).level
        if level in levels:
            raise ValueError(f"two extracts for level {level}")
        levels[level] = series
    if "850hPa" in levels:
        if "10m" not in levels:
            raise ValueError("the 850hPa check needs the 10m extract for path rain")
        surface = levels["10m"]
        levels["850hPa"] = {
            box: met_mod.with_surface_precip(upper, surface[box])
            for box, upper in levels["850hPa"].items()
        }
    return levels


def _level_document(
    h0: H0Report, met: dict[str, MetSeries], fires: Any, refs: tuple[SourceRef, ...]
) -> dict[str, Any]:
    ending = run_h1(h0, met, fires, refs, HourConvention.HOUR_ENDING)
    beginning = run_h1(h0, met, fires, refs, HourConvention.HOUR_BEGINNING)
    return {
        "report": ending.model_dump(mode="json"),
        "digest": output_digest(ending),
        "time_sensitive_boxes": time_sensitive_boxes(ending, beginning),
    }


def cmd_h1(args: argparse.Namespace) -> int:
    h0 = load_h0(args.nea)
    if not args.met:
        write_report(fallback_report(h0, "no pinned ERA5 extract was given"), args.out)
        print(f"H1 fallback (PM2.5 only, wind not checked) -> {args.out}")
        return 0
    detections, fire_refs = read_fires(args.firms)
    levels = {
        level: _level_document(h0, met, detections, fire_refs)
        for level, met in sorted(met_by_level(args.met).items())
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    document = {"h0_digest": output_digest(h0), "levels": levels}
    args.out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"H1 transport plausibility ({', '.join(levels)}) -> {args.out}")
    return 0


def cmd_base_rate(args: argparse.Namespace) -> int:
    snapshot, path = open_snapshot(args.nea)
    dataset = load_pm25(path, snapshot)
    h0 = describe(dataset, H1_WINDOW)
    levels = {
        level: run_base_rate(h0, dataset, met).model_dump(mode="json")
        for level, met in sorted(met_by_level(args.met).items())
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    document = {"h0_digest": output_digest(h0), "levels": levels}
    args.out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"H1 base rate ({', '.join(levels)}) -> {args.out}")
    return 0


def verify_manifest(manifest: Path, approvals_dir: Path) -> list[str]:
    """Problems with a download: hash or size against its manifest, total against its cap."""
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    problems: list[str] = []
    for entry in raw["files"]:
        path = manifest.parent / entry["file"]
        if not path.is_file():
            problems.append(f"{entry['file']}: missing")
            continue
        if file_digest(path) != entry["sha256"]:
            problems.append(f"{entry['file']}: sha256 differs from the manifest")
        if path.stat().st_size != entry["bytes"]:
            problems.append(f"{entry['file']}: size differs from the manifest")
    caps = {a.approval_id: a.max_bytes for a in load_approvals(approvals_dir)}
    cap = caps.get(raw.get("approval_id", ""))
    if cap is None:
        problems.append(f"approval {raw.get('approval_id')} has no recorded byte cap")
    elif raw["total_bytes"] > cap:
        problems.append(f"total {raw['total_bytes']} bytes exceeds the {cap}-byte cap")
    return problems


def cmd_verify(args: argparse.Namespace) -> int:
    raw = json.loads(args.manifest.read_text(encoding="utf-8"))
    for entry in raw["files"]:
        print(f"{entry['file']}  {entry['bytes']} bytes  sha256 {entry['sha256']}")
    problems = verify_manifest(args.manifest, args.approvals)
    print("\n".join(problems) if problems else f"OK: {raw['asset_id']}, {raw['total_bytes']} bytes")
    return 1 if problems else 0


def add_haze_parsers(sub: Any) -> None:
    h0 = sub.add_parser("haze-h0", help="H0: describe pinned NEA PM2.5 for Sep-Oct 2015")
    h0.add_argument("--nea", type=Path, default=Path("data/nea"))
    h0.add_argument("--out", type=Path, required=True)
    h0.set_defaults(func=cmd_h0)

    ext = sub.add_parser("haze-era5-extract", help="corridor-mean ERA5 series for each box")
    ext.add_argument("--manifest", type=Path, required=True)
    ext.add_argument("--level", choices=["10m", "850hPa"], default="10m")
    ext.add_argument("--out", type=Path, required=True)
    ext.set_defaults(func=cmd_extract)

    h1 = sub.add_parser("haze-h1", help="H1 sector diagnostic, or the PM2.5-only fallback")
    h1.add_argument("--nea", type=Path, default=Path("data/nea"))
    h1.add_argument("--met", type=Path, action="append", default=[])
    h1.add_argument("--firms", type=Path, action="append", default=[])
    h1.add_argument("--out", type=Path, required=True)
    h1.set_defaults(func=cmd_h1)

    rate = sub.add_parser("haze-base-rate", help="how often the H1 check passes in all hours")
    rate.add_argument("--nea", type=Path, default=Path("data/nea"))
    rate.add_argument("--met", type=Path, action="append", required=True)
    rate.add_argument("--out", type=Path, required=True)
    rate.set_defaults(func=cmd_base_rate)

    ver = sub.add_parser("haze-verify", help="check a download against its manifest and cap")
    ver.add_argument("--manifest", type=Path, required=True)
    ver.add_argument("--approvals", type=Path, default=Path("config/approvals"))
    ver.set_defaults(func=cmd_verify)
