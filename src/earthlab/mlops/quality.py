"""Dataset validation. It reports each problem and changes nothing."""

from __future__ import annotations

import numpy as np

from earthlab.mlops.contracts import ColumnQuality, DatasetSchemaV1, QualityReportV1


def _column(
    rule_name: str, data: np.ndarray, low: float | None, high: float | None
) -> ColumnQuality:
    missing = int(np.isnan(data).sum())
    known = data[~np.isnan(data)]
    return ColumnQuality(
        name=rule_name,
        missing=missing,
        below_range=int((known < low).sum()) if low is not None else 0,
        above_range=int((known > high).sum()) if high is not None else 0,
        coverage=round(1 - missing / max(len(data), 1), 6),
    )


def validate(
    schema: DatasetSchemaV1,
    stamps: np.ndarray,
    values: np.ndarray,
    names: tuple[str, ...],
    units: tuple[str, ...],
    source_sha256: str,
) -> QualityReportV1:
    """Stamps are integer positions on the cadence grid. Rows stay in file order."""
    issues: list[str] = []
    expected = tuple(c.name for c in schema.columns)
    if names != expected:
        issues.append(f"columns {names} differ from the schema {expected}")
    wanted = tuple(c.unit for c in schema.columns)
    if units != wanted:
        issues.append(f"units {units} differ from the schema {wanted}")
    if values.ndim != 2 or values.shape[0] != len(stamps) or values.shape[1] != len(names):
        raise ValueError("values must have shape (rows, columns) and match the stamps")
    steps = np.diff(stamps)
    duplicates = len(stamps) - len(np.unique(stamps))
    disorder = int((steps < 0).sum())
    first, last = (int(stamps.min()), int(stamps.max())) if len(stamps) else (0, -1)
    absent = max(last - first + 1 - len(np.unique(stamps)), 0)
    columns = tuple(
        _column(c.name, values[:, i], c.low, c.high)
        for i, c in enumerate(schema.columns[: values.shape[1]])
    )
    if duplicates:
        issues.append(f"{duplicates} duplicate timestamps")
    if disorder:
        issues.append(f"{disorder} timestamps out of order")
    for column in columns:
        if column.below_range or column.above_range:
            issues.append(f"{column.name}: values outside the declared range")
        if column.coverage < schema.min_coverage:
            issues.append(f"{column.name}: coverage {column.coverage} is below the minimum")
    return QualityReportV1(
        dataset_id=schema.dataset_id, source_sha256=source_sha256, rows=len(stamps),
        first_index=first, last_index=last, duplicate_stamps=duplicates, out_of_order=disorder,
        missing_stamps=absent, columns=columns, issues=tuple(issues),
    )  # fmt: skip
