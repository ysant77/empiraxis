"""PM2.5-only fallback for H1 when ERA5 is not pinned in time. Ceiling: observation.

The fallback reports the H0 events and the source-box geometry: the wind-from sector
each box would need. It never says that the 2015 wind was or was not in that sector.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from earthlab.contracts import Region, Strict
from earthlab.haze.contracts import EvidenceClass
from earthlab.haze.evidence import Provenance, output_digest
from earthlab.haze.geometry import H1_SOURCE_BOXES, GeometryRow, geometry_row
from earthlab.haze.h0 import H0Report

METHOD_ID = "haze-h1-fallback-pm25-only"
METHOD_VERSION = "1"
WIND_STATEMENT = "Not checked against 2015 wind data."
TOLERANCE_DEG = 45.0


class FallbackEvent(Strict):
    start_sgt: datetime
    end_sgt: datetime
    peak_ug_m3: float
    peak_region: Region
    wind_status: Literal["not_checked"] = "not_checked"


class FallbackReport(Strict):
    reason: str
    h0_digest: str
    events: tuple[FallbackEvent, ...]
    geometry: tuple[GeometryRow, ...]
    wind_statement: str
    provenance: Provenance


def fallback_report(h0: H0Report, reason: str) -> FallbackReport:
    return FallbackReport(
        reason=reason,
        h0_digest=output_digest(h0),
        events=tuple(
            FallbackEvent(
                start_sgt=e.start, end_sgt=e.end, peak_ug_m3=e.peak_ug_m3, peak_region=e.peak_region
            )
            for e in h0.events
        ),
        geometry=tuple(geometry_row(s, TOLERANCE_DEG) for s in H1_SOURCE_BOXES),
        wind_statement=WIND_STATEMENT,
        provenance=Provenance(
            evidence_class=EvidenceClass.OBSERVATION,
            method_id=METHOD_ID,
            method_version=METHOD_VERSION,
            sources=h0.provenance.sources,
            limitations=(
                *h0.provenance.limitations,
                "Geometry gives the wind-from sector a box needs; 2015 wind is not checked.",
                "No transport plausibility claim is made without wind and rain data.",
            ),
            parameters={"sector_tolerance_deg": TOLERANCE_DEG},
            synthetic=h0.provenance.synthetic,
        ),
    )
