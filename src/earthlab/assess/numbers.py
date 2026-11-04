"""Numbers in free text that must come from the evidence package.

Decimals (rule m41-v1, unchanged): every decimal number is a measurement.

Integers (rule m41-v3, prospective): an integer is a measurement when a unit follows it
("7 ug/m3", "45%", "42 days") or a metric word comes just before it ("MAE of 12"). These are
not measurements: identifiers that touch a letter or sign (R2, T+6, p15), years without a unit,
dates and times, and thresholds ("above 55", "> 55"). A model cannot change this rule.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

TOLERANCE = 0.005
DECIMAL = re.compile(r"(?<![\w.])-?\d+\.\d+(?![\w.])")
INTEGER = re.compile(r"(?<![\w.+\-/:])-?\d+(?![\w.:/\-]|\.\d)")
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_UNIT = re.compile(
    r"^\s?(%|percent\b|µg/m³|ug/m3|ug/m³|µg/m3|ugm-3)"
    r"|^\s([a-z-]+\s)?(days?|hours?|h|events?|episodes?|issues?|pixels?|cells?|stations?"
    r"|samples?|onsets?)\b",
    re.I,
)
_METRIC = re.compile(
    r"\b(mae|rmse|bias|skill|brier|auc|f1|error|rate|share|fraction|count|rho)\b"
    r"[^.\d]{0,16}$",
    re.I,
)
_THRESHOLD = re.compile(r"(above|below|over|under|exceed\w*|threshold|[<>≤≥]=?)\s*$", re.I)
_YEARS = range(1900, 2101)


def close(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOLERANCE * abs(b), 0.001)


def _grounded_decimal(text: str, values: list[float]) -> bool:
    number = float(text)
    places = len(text.split(".")[1])
    return any(round(v, places) == number or close(number, v) for v in values)


def _grounded_integer(n: int, percent: bool, values: list[float]) -> bool:
    """An integer is a rounded value: within half a unit (or half a percent point)."""
    if any(abs(n - v) <= 0.5 + 1e-9 for v in values):
        return True
    return percent and any(abs(n - v * 100) <= 0.5 + 1e-9 for v in values)


def integer_measurements(text: str) -> list[tuple[int, bool]]:
    """Integers that the text presents as measurements, with a flag for a percent sign."""
    out = []
    for m in INTEGER.finditer(text):
        before, after = text[: m.start()], text[m.end() :]
        if _THRESHOLD.search(before):
            continue
        unit = _UNIT.search(after)
        n = int(m.group())
        if unit is None and (n in _YEARS or not _METRIC.search(before)):
            continue
        percent = unit is not None and unit.group(1) is not None and unit.group(1)[:1] in "%p"
        out.append((n, percent))
    return out


def ungrounded(texts: Iterable[str], values: list[float]) -> list[str]:
    """Measurements in the texts that no package value supports."""
    out: list[str] = []
    for t in texts:
        out += [d for d in DECIMAL.findall(t) if not _grounded_decimal(d, values)]
        out += [
            f"{n}%" if p else str(n)
            for n, p in integer_measurements(t)
            if not _grounded_integer(n, p, values)
        ]
    return out
