"""The deterministic side of the delegation: the read-only tool and the acceptance checks.

Both read pinned rasters through the same month report that the verifier checks. A row the
specialist submits passes only if a fresh recomputation gives the same values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from earthlab.cases.loader import CaseFile
from earthlab.science.burned_area import QaPolicy
from earthlab.team.contracts import AcceptanceV1, CheckResult, QaRowV1
from earthlab.tools.burned_area_tools import month_report

FRACTION_TOLERANCE = 1e-4
AREA_TOLERANCE_HA = 0.05
CHECKS = (
    "every requested month and QA policy has exactly one row",
    "every value matches an independent recomputation from the pinned file",
    "a month below the reporting gate states no area",
)


def qa_row(case_file: CaseFile, root: Path, month: str, policy: str) -> tuple[QaRowV1, str]:
    """One recomputed row and the hash of the pinned file it read."""
    report: dict[str, Any] = month_report(case_file, root, month, QaPolicy(policy))
    summary = report["summary"]
    passed = bool(summary["gate_passed"])
    row = QaRowV1(
        month=month,
        qa_policy=policy,
        valid_fraction=round(float(summary["valid_fraction"]), 6),
        gate_passed=passed,
        area_ha=float(summary["primary_area_ha"]) if passed else None,
    )
    return row, str(report["source"]["sha256"])


def _same(row: QaRowV1, truth: QaRowV1) -> bool:
    if row.gate_passed != truth.gate_passed:
        return False
    if abs(row.valid_fraction - truth.valid_fraction) > FRACTION_TOLERANCE:
        return False
    if row.area_ha is None or truth.area_ha is None:
        return row.area_ha is None and truth.area_ha is None
    return abs(row.area_ha - truth.area_ha) <= AREA_TOLERANCE_HA


def check_table(
    task_id: str, rows: tuple[QaRowV1, ...], truth: dict[tuple[str, str], QaRowV1]
) -> AcceptanceV1:
    keys = [(r.month, r.qa_policy) for r in rows]
    missing = sorted(set(truth) - set(keys))
    extra = sorted(set(keys) - set(truth))
    repeated = len(keys) != len(set(keys))
    wrong = [r for r in rows if (r.month, r.qa_policy) in truth]
    wrong = [r for r in wrong if not _same(r, truth[(r.month, r.qa_policy)])]
    invented = [r for r in rows if not r.gate_passed and r.area_ha is not None]
    results = (
        CheckResult(
            name=CHECKS[0],
            passed=not missing and not extra and not repeated,
            detail=f"missing {missing}, extra {extra}, repeated {repeated}",
        ),
        CheckResult(
            name=CHECKS[1],
            passed=not wrong,
            detail=f"{len(wrong)} of {len(rows)} rows differ",
        ),
        CheckResult(name=CHECKS[2], passed=not invented, detail=f"{len(invented)} rows"),
    )
    return AcceptanceV1(task_id=task_id, passed=all(c.passed for c in results), checks=results)
