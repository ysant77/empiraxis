"""The scientific label of the NEA experiments, from the suitability checks.

NEA publishes no available-at time. The protocol models it as label + 1 h + latency, so these
runs are simulated-availability hindcasts. They are not prospective forecasts, and they are
not hindsight reanalysis. The check runs before any method, on the rows before the sealed test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from earthlab.digest import file_digest
from earthlab.forecast import samples as S
from earthlab.forecast.dataset import label_at
from earthlab.harness.audit import NEA_URL, SINGAPORE
from earthlab.harness.suitability import (
    AlignmentReportV1,
    DatasetSuitabilityV1,
    JoinPlanV1,
    VariableSpec,
    preflight,
)

LABEL = "simulated_availability_hindcast"
DATASET = "nea-historical-1hr-pm25"
PINNED_NEA = "2fb76e1c4e4208e92f49670602e303c86e21eaa3704651633323e50f51015de4"
SGT = timezone(timedelta(hours=8))
ALIGNMENT_FILE = "alignment-report.json"


class NotAlignable(ValueError):
    """The suitability check blocked this experiment. No method ran."""


def _local(index: int) -> datetime:
    return label_at(index).replace(tzinfo=SGT)


def nea_profile(source: Path, values: np.ndarray) -> DatasetSuitabilityV1:
    """Facts measured from this file, up to the last row before the sealed period."""
    return DatasetSuitabilityV1(
        dataset_id=DATASET, revision="source updated 2026-10-20", source_url=NEA_URL,
        variables=(VariableSpec(name="pm25", unit="ug/m3"),), grid="five NEA regions",
        area=SINGAPORE, first_time=_local(0), last_time=_local(len(values) - 1),
        cadence_hours=1.0, spatial_support="region", event_time="unknown", valid_time="unknown",
        data_kind="observation", availability="modelled", latency_hours=float(S.LATENCY_HOURS),
        missing_fraction=float(np.isnan(values).mean()),
        license="Singapore Open Data Licence v1.0", local_state="verified",
        local_sha256=file_digest(source), permission="not_required",
        allowed_evidence=("historical_research", LABEL),
        notes=("availability is the protocol's rule, not a logged time",),
    )  # fmt: skip


def nea_plan(rows: int) -> JoinPlanV1:
    return JoinPlanV1(
        target_id="nea-pm25-history", arm=LABEL, inputs=(DATASET,), aoi=SINGAPORE,
        window_start=_local(0), window_end=_local(rows - 1),
        expected_units={"pm25": "ug/m3"}, target_cadence_hours=1.0, target_support="region",
        evaluation_start=_local(S.SEALED_FROM),
    )  # fmt: skip


def check(source: Path, values: np.ndarray) -> AlignmentReportV1:
    return preflight(nea_plan(len(values)), [nea_profile(source, values)])


def require(folder: Path, source: Path, values: np.ndarray) -> AlignmentReportV1:
    """Save the report, and refuse the run when a blocking finding exists."""
    report = check(source, values)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ALIGNMENT_FILE).write_text(report.model_dump_json(indent=2), encoding="utf-8")
    if report.verdict == "not_alignable":
        raise NotAlignable("; ".join(f.detail for f in report.findings if f.blocking))
    return report
