"""H1: wind and rain sector diagnostic over H0 event onsets and matched control hours.

Evidence class: transport plausibility. For each onset and source box the lagged sector
check runs; event onsets are compared with control onsets (the base rate), and the
negative controls from the design are counted. Nothing here estimates a concentration
or attributes PM2.5 to a source.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

from earthlab.contracts import SGT, Strict
from earthlab.haze.contracts import EvidenceClass
from earthlab.haze.evidence import Provenance, SourceRef
from earthlab.haze.fires import FireDetection, count_in_window
from earthlab.haze.geometry import H1_SOURCE_BOXES, GeometryRow, SourceBox, geometry_row
from earthlab.haze.h0 import H0Report
from earthlab.haze.sector import H1Params, LagCheck, MetSeries, TransportStatus, combine, lag_check
from earthlab.haze.timebase import HourConvention, nea_label_to_utc_interval

METHOD_ID = "haze-h1-sector-diagnostic"
METHOD_VERSION = "1"
CONTROL_LABEL_HOUR_SGT = 14
CONTROL_CLEAR_HOURS = 24
MIN_ONSETS = 3
LIMITATIONS = (
    "Transport plausibility only: wind and rain consistent or not with transport from a box.",
    "Wind direction cannot give a PM2.5 concentration; emissions, mixing and deposition matter.",
    "ERA5 is a 0.25 degree reanalysis; land-sea breeze and smoke height are not resolved.",
    "Straight-line geometry; real paths curve. No trajectory or dispersion model is used.",
    "FIRMS misses fires under cloud and smoke and small or cool fires; zero is not none.",
    "A temporal association does not establish causation.",
)

Kind = Literal["event", "control"]


class BoxDiagnostic(Strict):
    box_id: str
    status: TransportStatus
    fire_detections: int
    lags: tuple[LagCheck, ...]
    notes: tuple[str, ...]


class OnsetDiagnostic(Strict):
    kind: Kind
    label_sgt: datetime
    onset_utc: datetime
    boxes: tuple[BoxDiagnostic, ...]


class BoxSummary(Strict):
    box_id: str
    event_onsets: int
    event_consistent: int
    control_onsets: int
    control_consistent: int
    association: Literal["higher_in_events", "not_higher", "insufficient"]


class NegativeControl(Strict):
    control_id: str
    description: str
    count: int | None
    examples: tuple[datetime, ...]


class H1Report(Strict):
    hour_convention: HourConvention
    level: str
    params: H1Params
    geometry: tuple[GeometryRow, ...]
    onsets: tuple[OnsetDiagnostic, ...]
    summaries: tuple[BoxSummary, ...]
    negative_controls: tuple[NegativeControl, ...]
    provenance: Provenance


def control_labels(h0: H0Report) -> list[datetime]:
    """Each day's 14:00 SGT label when it is a control-quality hour and clear of events."""
    labels: list[datetime] = []
    day = h0.window.start.astimezone(SGT).replace(hour=CONTROL_LABEL_HOUR_SGT, minute=0)
    clear = timedelta(hours=CONTROL_CLEAR_HOURS)
    while day < h0.window.end:
        near = any(e.start - clear <= day < e.end + clear for e in h0.events)
        if not near and day >= h0.window.start:
            labels.append(day)
        day += timedelta(days=1)
    return labels


def _note(status: TransportStatus, fires: int) -> tuple[str, ...]:
    notes = []
    if fires == 0:
        notes.append(
            "No detections in the box; cloud and smoke hide fires, so this is not no fires."
        )
    if status is TransportStatus.CONSISTENT:
        notes.append("Wind and rain are consistent with transport from this box; not attribution.")
    return tuple(notes)


def _box(
    source: SourceBox, met: MetSeries, fires: list[FireDetection], onset: datetime, params: H1Params
) -> BoxDiagnostic:
    lookup = met.lookup()
    checks = [lag_check(lookup, source, onset, lag, params) for lag in params.lags_hours]
    status = combine(checks)
    start = onset - timedelta(hours=max(params.lags_hours))
    count = count_in_window(fires, source, start, onset, params.fire_min_confidence)
    return BoxDiagnostic(
        box_id=source.box_id,
        status=status,
        fire_detections=count,
        lags=tuple(checks),
        notes=_note(status, count),
    )


def _onset(
    kind: Kind,
    label: datetime,
    met: dict[str, MetSeries],
    fires: dict[str, list[FireDetection]],
    convention: HourConvention,
    params: H1Params,
) -> OnsetDiagnostic:
    onset_utc, _ = nea_label_to_utc_interval(label, convention)
    boxes = tuple(
        _box(s, met[s.box_id], fires.get(s.box_id, []), onset_utc, params) for s in H1_SOURCE_BOXES
    )
    return OnsetDiagnostic(kind=kind, label_sgt=label, onset_utc=onset_utc, boxes=boxes)


def _summary(box_id: str, onsets: list[OnsetDiagnostic]) -> BoxSummary:
    def tally(kind: Kind) -> tuple[int, int]:
        rows = [b for o in onsets if o.kind == kind for b in o.boxes if b.box_id == box_id]
        decided = [b for b in rows if b.status is not TransportStatus.INCONCLUSIVE]
        return len(decided), sum(b.status is TransportStatus.CONSISTENT for b in decided)

    events, event_ok = tally("event")
    controls, control_ok = tally("control")
    if events < MIN_ONSETS or controls < MIN_ONSETS:
        association: Literal["higher_in_events", "not_higher", "insufficient"] = "insufficient"
    elif event_ok / events > control_ok / controls:
        association = "higher_in_events"
    else:
        association = "not_higher"
    return BoxSummary(
        box_id=box_id,
        event_onsets=events,
        event_consistent=event_ok,
        control_onsets=controls,
        control_consistent=control_ok,
        association=association,
    )


def _control(control_id: str, text: str, hits: list[datetime] | None) -> NegativeControl:
    count = None if hits is None else len(hits)
    return NegativeControl(
        control_id=control_id, description=text, count=count, examples=tuple((hits or [])[:5])
    )


def _consistent_with_fires(onset: OnsetDiagnostic) -> bool:
    return any(
        b.status is TransportStatus.CONSISTENT and b.fire_detections > 0 for b in onset.boxes
    )


def _no_detections(onset: OnsetDiagnostic) -> bool:
    return all(b.fire_detections == 0 for b in onset.boxes)


def _never_consistent(onset: OnsetDiagnostic) -> bool:
    return all(b.status is not TransportStatus.CONSISTENT for b in onset.boxes)


def _where(
    onsets: list[OnsetDiagnostic], kind: Kind, test: Callable[[OnsetDiagnostic], bool]
) -> list[datetime]:
    return [o.label_sgt for o in onsets if o.kind == kind and test(o)]


def negative_controls(onsets: list[OnsetDiagnostic]) -> tuple[NegativeControl, ...]:
    """The design's negative controls, counted where the data allow it."""
    return (
        _control(
            "fire_upwind_no_pm25_rise",
            "Control hours: wind consistent with transport from a box with detections, "
            "but PM2.5 at or below 55 ug/m3.",
            _where(onsets, "control", _consistent_with_fires),
        ),
        _control(
            "pm25_rise_without_upwind_detections",
            "Event onsets with zero detections in every box.",
            _where(onsets, "event", _no_detections),
        ),
        _control(
            "rain_or_wind_shift",
            "Event onsets where no box is consistent (rain, wind shift or missing data).",
            _where(onsets, "event", _never_consistent),
        ),
        _control(
            "haze_looking_visibility_normal_pm25",
            "Not testable: v1 has no visibility data. Visibility is not PM2.5.",
            None,
        ),
        _control(
            "association_not_cause",
            "Any association here is temporal. The report class is transport plausibility.",
            None,
        ),
        _control(
            "reanalysis_as_forecast",
            "Not applicable: H1 is retrospective. FeatureSet refuses look-ahead inputs.",
            None,
        ),
    )


def run_h1(
    h0: H0Report,
    met: dict[str, MetSeries],
    fires: dict[str, list[FireDetection]],
    fire_sources: tuple[SourceRef, ...],
    convention: HourConvention = HourConvention.HOUR_ENDING,
    params: H1Params | None = None,
    synthetic: bool = False,
) -> H1Report:
    params = params or H1Params()
    missing = [s.box_id for s in H1_SOURCE_BOXES if s.box_id not in met]
    if missing:
        raise ValueError(f"no wind series for {missing}; use the PM2.5-only fallback")
    labels: list[tuple[Kind, datetime]] = [("event", e.start) for e in h0.events]
    labels += [("control", label) for label in control_labels(h0)]
    onsets = [_onset(kind, label, met, fires, convention, params) for kind, label in labels]
    levels = {series.level for series in met.values()}
    met_refs = tuple(dict.fromkeys(ref for s in met.values() for ref in s.sources))
    return H1Report(
        hour_convention=convention,
        level="+".join(sorted(levels)),
        params=params,
        geometry=tuple(geometry_row(s, params.tolerance_deg) for s in H1_SOURCE_BOXES),
        onsets=tuple(onsets),
        summaries=tuple(_summary(s.box_id, onsets) for s in H1_SOURCE_BOXES),
        negative_controls=negative_controls(onsets),
        provenance=Provenance(
            evidence_class=EvidenceClass.TRANSPORT_PLAUSIBILITY,
            method_id=METHOD_ID,
            method_version=METHOD_VERSION,
            sources=h0.provenance.sources + met_refs + fire_sources,
            limitations=LIMITATIONS,
            parameters={
                "hour_convention": convention.value,
                "control_label_hour_sgt": CONTROL_LABEL_HOUR_SGT,
            },
            synthetic=synthetic or h0.provenance.synthetic,
        ),
    )


def time_sensitive_boxes(ending: H1Report, beginning: H1Report) -> list[str]:
    """Boxes whose event-onset statuses change between the two NEA hour conventions."""
    changed: set[str] = set()
    for a, b in zip(ending.onsets, beginning.onsets, strict=True):
        changed |= {
            x.box_id for x, y in zip(a.boxes, b.boxes, strict=True) if x.status is not y.status
        }
    return sorted(changed)
