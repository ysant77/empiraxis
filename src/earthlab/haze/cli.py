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

from earthlab.contracts import SGT, Strict, TimeWindow
from earthlab.data.nea_pm25 import load_pm25
from earthlab.data.snapshot import open_snapshot
from earthlab.haze import fires as fires_mod
from earthlab.haze import met as met_mod
from earthlab.haze.evidence import SourceRef, output_digest
from earthlab.haze.fallback import fallback_report
from earthlab.haze.geometry import H1_SOURCE_BOXES, corridor
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


def load_decoder() -> met_mod.GridDecoder:
    raise met_mod.DecoderMissing(
        "no GRIB decoder is installed; adding eccodes needs owner approval"
    )


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
    for manifest in manifests:
        detections, file_refs = fires_mod.read_manifest(manifest)
        asset = json.loads(manifest.read_text(encoding="utf-8"))["asset_id"]
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


def cmd_h1(args: argparse.Namespace) -> int:
    h0 = load_h0(args.nea)
    if not args.met:
        write_report(fallback_report(h0, "no pinned ERA5 extract was given"), args.out)
        print(f"H1 fallback (PM2.5 only, wind not checked) -> {args.out}")
        return 0
    met: dict[str, MetSeries] = {}
    for path in args.met:
        met.update(read_extract(path))
    detections, fire_refs = read_fires(args.firms)
    ending = run_h1(h0, met, detections, fire_refs, HourConvention.HOUR_ENDING)
    beginning = run_h1(h0, met, detections, fire_refs, HourConvention.HOUR_BEGINNING)
    sensitive = time_sensitive_boxes(ending, beginning)
    write_report(ending, args.out, {"time_sensitive_boxes": sensitive})
    print(f"H1 transport plausibility -> {args.out}; time-sensitive boxes: {sensitive or 'none'}")
    return 0


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
