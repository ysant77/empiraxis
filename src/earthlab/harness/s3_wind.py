"""S3: is the 2015 wind and rain record retrospectively consistent with transport from a box?

This reuses the H0 and H1 code. It adds the explicit wind and rain checks, a grid of
sensitivity runs and one fixed rule for the verdict. The verdict is consistent, inconsistent
or inconclusive. It is never a source attribution, and it is not a prediction. ERA5 is a
reanalysis, so this is a perfect-weather hindsight diagnostic.
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path
from typing import Literal, NamedTuple

from earthlab.contracts import Strict
from earthlab.data.nea_pm25 import Pm25Dataset, load_pm25
from earthlab.data.snapshot import open_snapshot
from earthlab.haze.base_rate import BaseRateReport, run_base_rate
from earthlab.haze.cli import H1_WINDOW, met_by_level
from earthlab.haze.h0 import H0Report, describe
from earthlab.haze.sector import H1Params, MetSeries
from earthlab.haze.timebase import HourConvention
from earthlab.haze.transport_checks import (
    ClockCheck,
    PrecipCheck,
    SignResult,
    check_clock,
    check_precip,
    sign_tests,
)

Verdict = Literal["consistent", "inconsistent", "inconclusive"]
MIN_EVENT_DECIDED = 10
MIN_CLEAN_DECIDED = 20
CONSISTENT_EVENT_RATE = 0.5
MIN_LIFT = 0.2
INCONSISTENT_EVENT_RATE = 0.25
STABLE_SHARE = 0.8
TOLERANCES = (30.0, 45.0, 60.0)
RAIN_LIMITS = (0.5, 1.0, 2.0)
LAG_SETS = ((12, 24), (24, 48), (12, 24, 36, 48, 72))
STATEMENT = (
    "Retrospective consistency of wind and rain with transport from a box. "
    "A temporal association is not a cause. This is not a source attribution."
)


class Setting(NamedTuple):
    tolerance_deg: float
    rain_limit_mm_h: float
    lags_hours: tuple[int, ...]
    convention: HourConvention


class VariantRate(Strict):
    tolerance_deg: float
    rain_limit_mm_h: float
    lags_hours: tuple[int, ...]
    convention: HourConvention
    event_rate: float | None
    clean_rate: float | None
    event_decided: int
    clean_decided: int
    verdict: Verdict


class BoxVerdict(Strict):
    box_id: str
    level: str
    verdict: Verdict
    stable_share: float
    base_event_rate: float | None
    base_clean_rate: float | None
    sensitivity: float | None
    specificity: float | None
    variants: tuple[VariantRate, ...]


class S3Report(Strict):
    statement: str = STATEMENT
    evidence_class: str = "perfect-weather hindsight diagnostic (ERA5 reanalysis)"
    sign_tests: tuple[SignResult, ...]
    clocks: tuple[ClockCheck, ...]
    precip: dict[str, PrecipCheck]
    boxes: tuple[BoxVerdict, ...]
    overall: Verdict
    identifiable_source: bool
    notes: tuple[str, ...]


def decide(event: float | None, clean: float | None, n_event: int, n_clean: int) -> Verdict:
    """The fixed rule. Few decided hours, or a high pass rate in clean hours, is inconclusive."""
    if n_event < MIN_EVENT_DECIDED or n_clean < MIN_CLEAN_DECIDED:
        return "inconclusive"
    if event is None or clean is None:
        return "inconclusive"
    if event >= CONSISTENT_EVENT_RATE and event - clean >= MIN_LIFT:
        return "consistent"
    if event < INCONSISTENT_EVENT_RATE:
        return "inconsistent"
    return "inconclusive"


def _group(report: BaseRateReport, box: str, name: str) -> tuple[float | None, int]:
    row = next(b for b in report.boxes if b.box_id == box)
    group = next(g for g in row.groups if g.group == name)
    return group.rate, group.decided


def _variant(
    h0: H0Report, data: Pm25Dataset, met: dict[str, MetSeries], setting: Setting
) -> dict[str, VariantRate]:
    tol, rain, lags, convention = setting
    params = H1Params(tolerance_deg=tol, rain_limit_mm_h=rain, lags_hours=lags)
    report = run_base_rate(h0, data, met, convention, params)
    out = {}
    for box in met:
        event, n_event = _group(report, box, "event_onsets")
        clean, n_clean = _group(report, box, "clean_at_or_below_55")
        out[box] = VariantRate(
            tolerance_deg=tol, rain_limit_mm_h=rain, lags_hours=lags, convention=convention,
            event_rate=event, clean_rate=clean, event_decided=n_event, clean_decided=n_clean,
            verdict=decide(event, clean, n_event, n_clean),
        )  # fmt: skip
    return out


def _is_base(r: VariantRate) -> bool:
    """The H1 default settings, reported as the headline sensitivity and specificity."""
    default = (r.tolerance_deg, r.rain_limit_mm_h, r.lags_hours)
    return default == (45.0, 1.0, LAG_SETS[-1]) and r.convention is HourConvention.HOUR_ENDING


def _box_verdict(box: str, level: str, runs: list[VariantRate]) -> BoxVerdict:
    votes = [r.verdict for r in runs]
    best = max(set(votes), key=votes.count)
    share = votes.count(best) / len(votes)
    final: Verdict = best if share >= STABLE_SHARE else "inconclusive"
    base = next(r for r in runs if _is_base(r))
    clean = base.clean_rate
    return BoxVerdict(
        box_id=box, level=level, verdict=final, stable_share=round(share, 3),
        base_event_rate=base.event_rate, base_clean_rate=clean,
        sensitivity=base.event_rate,
        specificity=None if clean is None else round(1 - clean, 3), variants=tuple(runs),
    )  # fmt: skip


def run_s3(nea_dir: Path, extracts: list[Path]) -> S3Report:
    snapshot, path = open_snapshot(nea_dir)
    data = load_pm25(path, snapshot)
    h0 = describe(data, H1_WINDOW)
    levels = met_by_level(extracts)
    grid = [
        Setting(*g) for g in itertools.product(TOLERANCES, RAIN_LIMITS, LAG_SETS, HourConvention)
    ]
    boxes: list[BoxVerdict] = []
    clocks: list[ClockCheck] = []
    precip: dict[str, PrecipCheck] = {}
    for level, met in sorted(levels.items()):
        runs = [_variant(h0, data, met, g) for g in grid]
        boxes += [_box_verdict(b, level, [r[b] for r in runs]) for b in sorted(met)]
        clocks += [check_clock(series) for series in met.values()]
        if level == "10m":
            precip = {b: check_precip([h.precip_mm for h in s.hours]) for b, s in met.items()}
    return _report(boxes, clocks, precip)


def _report(
    boxes: list[BoxVerdict], clocks: list[ClockCheck], precip: dict[str, PrecipCheck]
) -> S3Report:
    consistent = {b.box_id for b in boxes if b.verdict == "consistent"}
    all_incon = all(b.verdict == "inconsistent" for b in boxes)
    overall: Verdict = (
        "consistent" if consistent else "inconsistent" if all_incon else "inconclusive"
    )
    notes = [
        "More than one box passing means the source is not identifiable from wind alone."
        if len(consistent) > 1 else "A single passing box still does not identify a source.",
        "Some FIRMS detections, most in box B, carry the static land type flag: not all are fires.",
        "The two months are haze-heavy. The result does not carry to other years.",
    ]  # fmt: skip
    return S3Report(
        sign_tests=sign_tests(), clocks=tuple(clocks), precip=precip, boxes=tuple(boxes),
        overall=overall, identifiable_source=False, notes=tuple(notes),
    )  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S3 wind and rain consistency, 2015.")
    parser.add_argument("--nea", type=Path, default=Path("data/nea"))
    parser.add_argument("--met", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_s3(args.nea, args.met)
    args.out.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    for b in report.boxes:
        print(f"{b.level:7} {b.box_id}: {b.verdict} (stable {b.stable_share}) "
              f"sens {b.sensitivity} spec {b.specificity}")  # fmt: skip
    print(f"overall: {report.overall}; source identifiable: {report.identifiable_source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
