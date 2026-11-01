"""How often the H1 wind and rain check passes in all hours, not only at haze onsets.

H1 compares onsets with few control hours. This diagnostic applies the same check, with the
same parameters, to every hour with full lag history, grouped by the network peak PM2.5 of
that hour. A rate close to the clean-hour rate means that a pass tells little about haze.
Hours are autocorrelated, so the report states rates only and no significance. It does not
change H1 and it does not attribute PM2.5 to a source.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from earthlab.contracts import Strict
from earthlab.data.nea_pm25 import Pm25Dataset
from earthlab.haze.contracts import EvidenceClass
from earthlab.haze.evidence import Provenance
from earthlab.haze.geometry import H1_SOURCE_BOXES
from earthlab.haze.h0 import NORMAL_MAX, H0Report
from earthlab.haze.sector import H1Params, MetHour, MetSeries, TransportStatus, combine, lag_check
from earthlab.haze.timebase import HourConvention, nea_label_to_utc_interval

METHOD_ID = "haze-h1-base-rate"
METHOD_VERSION = "1"
HIGH_PM = 150.0
LIMITATIONS = (
    "Rates describe this two-month window only. Hours are autocorrelated: no significance.",
    "A pass is transport plausibility only. It is not attribution and not a prediction.",
)


class GroupRate(Strict):
    group: str
    hours: int
    decided: int
    consistent: int
    rate: float | None


class BoxRates(Strict):
    box_id: str
    groups: tuple[GroupRate, ...]


class BaseRateReport(Strict):
    level: str
    hour_convention: HourConvention
    hours_checked: int
    boxes: tuple[BoxRates, ...]
    provenance: Provenance


def _rate(group: str, statuses: list[TransportStatus]) -> GroupRate:
    consistent = statuses.count(TransportStatus.CONSISTENT)
    decided = consistent + statuses.count(TransportStatus.INCONSISTENT)
    rate = round(consistent / decided, 3) if decided else None
    return GroupRate(
        group=group, hours=len(statuses), decided=decided, consistent=consistent, rate=rate
    )


def _peak(dataset: Pm25Dataset, label: datetime) -> float | None:
    row = dataset.at(label)
    observed = [v for v in row.values.values() if v is not None] if row else []
    return max(observed) if observed else None


def _box_rates(
    box_index: int,
    lookup: dict[datetime, MetHour],
    labels: list[tuple[datetime, datetime, float | None, bool]],
    params: H1Params,
) -> BoxRates:
    source = H1_SOURCE_BOXES[box_index]
    rows = [
        (
            peak,
            onset_label,
            combine([lag_check(lookup, source, onset, lag, params) for lag in params.lags_hours]),
        )
        for onset, _, peak, onset_label in labels
    ]
    picks = {
        "all_hours": [s for _, _, s in rows],
        "clean_at_or_below_55": [s for p, _, s in rows if p is not None and p <= NORMAL_MAX],
        "above_150": [s for p, _, s in rows if p is not None and p > HIGH_PM],
        "event_onsets": [s for _, is_onset, s in rows if is_onset],
    }
    return BoxRates(
        box_id=source.box_id, groups=tuple(_rate(name, group) for name, group in picks.items())
    )


def run_base_rate(
    h0: H0Report,
    dataset: Pm25Dataset,
    met: dict[str, MetSeries],
    convention: HourConvention = HourConvention.HOUR_ENDING,
    params: H1Params | None = None,
) -> BaseRateReport:
    params = params or H1Params()
    lookups = {box: series.lookup() for box, series in met.items()}
    first = min(min(lookup) for lookup in lookups.values())
    history = timedelta(hours=max(params.lags_hours))
    onsets = {e.start for e in h0.events}
    labels = []
    for label in h0.window.hours():
        onset, _ = nea_label_to_utc_interval(label, convention)
        if onset - history >= first:
            labels.append((onset, label, _peak(dataset, label), label in onsets))
    boxes = tuple(
        _box_rates(i, lookups[s.box_id], labels, params) for i, s in enumerate(H1_SOURCE_BOXES)
    )
    return BaseRateReport(
        level="+".join(sorted({series.level for series in met.values()})),
        hour_convention=convention,
        hours_checked=len(labels),
        boxes=boxes,
        provenance=Provenance(
            evidence_class=EvidenceClass.TRANSPORT_PLAUSIBILITY,
            method_id=METHOD_ID,
            method_version=METHOD_VERSION,
            sources=h0.provenance.sources
            + tuple(dict.fromkeys(ref for s in met.values() for ref in s.sources)),
            limitations=LIMITATIONS,
            parameters={"hour_convention": convention.value, "high_pm_ug_m3": HIGH_PM},
            synthetic=h0.provenance.synthetic,
        ),
    )
