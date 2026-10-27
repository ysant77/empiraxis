"""Arm A: a deterministic natural-language dispatcher with the same tools as the agent.

It reads only the question text, never the scenario's expected outcome or requirements.
It calls the same registered tools (and so the same verifier) through the registry. Its
rules were written after reading the visible development questions, which favours it on
those questions; this is stated in every summary.
"""

from __future__ import annotations

import itertools
import json
import re
import time
from datetime import datetime, timedelta
from typing import Any

from earthlab.agent.area_findings import AreaLedger
from earthlab.agent.findings import FindingsLedger
from earthlab.agent.limitations import LimitationLog, ReasonCode
from earthlab.bench.scenarios import Outcome
from earthlab.contracts import MAX_WINDOW_DAYS, Region
from earthlab.runtime import Workspace, build_registry
from earthlab.tools.registry import ToolRegistry

_MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)  # fmt: skip
_MONTH = "|".join(_MONTHS)
_RANGE = re.compile(rf"\b({_MONTH})\s*(?:-|\u2013|to|and)\s*({_MONTH})\s+(\d{{4}})", re.I)
_SINGLE = re.compile(rf"\b({_MONTH})\s+(\d{{4}})", re.I)
_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_YEAR = re.compile(r"\b(19|20)(\d{2})\b")
_THRESHOLD = re.compile(r"(?:above|exceed\w*|over)\s+(\d+(?:\.\d+)?)", re.I)
_PM25_CUE = re.compile(r"PM\s?2\.5|\bNEA\b|[uµ]g\s*/\s*m3", re.I)
_REGION = re.compile(r"\b(north|south|east|west|central)\b", re.I)
_RULES: tuple[tuple[re.Pattern[str], ReasonCode], ...] = (
    (re.compile(r"\bhotspots?\b", re.I), ReasonCode.HOTSPOT_NOT_AREA),
    (re.compile(r"land[- ]surface temperature|\bLST\b", re.I), ReasonCode.LST_NOT_AIR_TEMPERATURE),
    (re.compile(r"\bcaus\w*|\bprove\b", re.I), ReasonCode.CAUSATION_NOT_IDENTIFIABLE),
    (re.compile(r"\bhindcast|\bpredict\w*", re.I), ReasonCode.HINDCAST_NOT_RUN),
    (re.compile(r"\bdeforestation\b", re.I), ReasonCode.DEFINITION_MISMATCH),
)
_CASES = {
    "uttarakhand": "uttarakhand-2024-burned-area",
    "kalimantan": "kalimantan-2015-burned-area",
}
_AREA_CUE = re.compile(r"\bhectares?\b|\bburned area\b|mapped as burned", re.I)
_CASE_CODES = {
    "blocked": ReasonCode.DATA_UNAVAILABLE,
    "needs_approval": ReasonCode.NEEDS_APPROVAL,
    "not_implemented": ReasonCode.METHOD_NOT_IMPLEMENTED,
}


def _month_start(year: int, month: int) -> datetime:
    return datetime(year + (month - 1) // 12, (month - 1) % 12 + 1, 1)


def parse_windows(question: str) -> list[tuple[datetime, datetime]]:
    """Windows named in the text; a bare year is split into tool-sized windows."""
    iso = _ISO.findall(question)
    if len(iso) >= 2:
        return [(datetime.fromisoformat(iso[0]), datetime.fromisoformat(iso[1]))]
    if m := _RANGE.search(question):
        first, last = _MONTHS.index(m[1].lower()) + 1, _MONTHS.index(m[2].lower()) + 1
        return [(_month_start(int(m[3]), first), _month_start(int(m[3]), last + 1))]
    if m := _SINGLE.search(question):
        month = _MONTHS.index(m[1].lower()) + 1
        return [(_month_start(int(m[2]), month), _month_start(int(m[2]), month + 1))]
    if m := _YEAR.search(question):
        start, end = datetime(int(m[0]), 1, 1), datetime(int(m[0]) + 1, 1, 1)
        step = timedelta(days=MAX_WINDOW_DAYS)
        edges = [start + i * step for i in range(int((end - start) / step) + 1)] + [end]
        return [(a, b) for a, b in itertools.pairwise(edges) if a < b]
    return []


class Dispatcher:
    def __init__(self, workspace: Workspace):
        self._workspace = workspace

    def run(self, question: str) -> Outcome:
        started = time.monotonic()
        ledger, limits, area = FindingsLedger(), LimitationLog(), AreaLedger()
        registry = build_registry(self._workspace, ledger, limits, area)
        calls = self._route(question, registry)
        codes = sorted(limits.codes())
        used = [led for led in (ledger, area) if led.rounds]
        verified = bool(used) and all(led.all_supported() for led in used)
        status = "abstained" if codes else "verified" if verified else "no_supported_findings"
        return Outcome(
            status=status,
            supported=ledger.supported(),
            area_supported=area.supported(),
            rejected_claims=len(ledger.rejected()) + len(area.rejected()),
            reason_codes=codes,
            seconds=round(time.monotonic() - started, 3),
            tool_calls=calls,
        )

    def _route(self, question: str, registry: ToolRegistry) -> int:
        for pattern, code in _RULES:
            if pattern.search(question):
                return self._abstain(registry, [code])
        for word, case_id in _CASES.items():
            if word in question.lower():
                report = self._call(registry, "assess_case", {"case_id": case_id})
                if report.get("status") == "feasible" and _AREA_CUE.search(question):
                    return 1 + self._burned_area(question, case_id, registry)
                code = _CASE_CODES.get(report.get("status", ""), ReasonCode.OUT_OF_SCOPE)
                return 1 + self._abstain(registry, [code])
        windows = parse_windows(question)
        if not windows or not _PM25_CUE.search(question):
            return self._abstain(registry, [ReasonCode.OUT_OF_SCOPE])
        return self._pm25(question, registry, windows)

    def _pm25(
        self, question: str, registry: ToolRegistry, windows: list[tuple[datetime, datetime]]
    ) -> int:
        regions = [Region(r.lower()) for r in _REGION.findall(question)]
        if re.search(r"exceed|above|threshold", question, re.I):
            found = _THRESHOLD.search(question)
            if found is None or not regions:
                return self._abstain(registry, [ReasonCode.NEEDS_INPUT])
            return self._hours_above(registry, windows[0], regions[0], float(found[1]))
        claims: list[dict[str, Any]] = []
        for start, end in windows:
            window = {"start": start.isoformat(), "end": end.isoformat()}
            if regions:
                rows = self._call(
                    registry, "summarize_regions", {**window, "regions": [regions[0].value]}
                )
                peak = rows["summaries"][0]["max"]
                claims.append(_claim("region_max", regions[0].value, window, value=peak))
            else:
                top = self._call(registry, "rank_regions", {**window, "statistic": "max"})[
                    "ranking"
                ][0]
                claims.append(_claim("peak_region", top["region"], window, value=top["value"]))
        self._call(registry, "submit_findings", {"claims": claims})
        return len(windows) + 1

    def _hours_above(
        self,
        registry: ToolRegistry,
        window: tuple[datetime, datetime],
        region: Region,
        threshold: float,
    ) -> int:
        args = {"start": window[0].isoformat(), "end": window[1].isoformat()}
        counted = self._call(
            registry, "count_hours_above", {**args, "region": region.value, "threshold": threshold}
        )
        rows = self._call(registry, "summarize_regions", {**args, "regions": [region.value]})
        claims = [
            _claim(
                "hours_above", region.value, args, value=counted["hours_above"], threshold=threshold
            ),
            _claim(
                "missing_hours", region.value, args, value=rows["summaries"][0]["missing_hours"]
            ),
        ]
        self._call(registry, "submit_findings", {"claims": claims})
        return 3

    def _burned_area(self, question: str, case_id: str, registry: ToolRegistry) -> int:
        windows = parse_windows(question)
        if len(windows) != 1:
            return self._abstain(registry, [ReasonCode.NEEDS_INPUT])
        month = f"{windows[0][0]:%Y-%m}"
        report = self._call(registry, "burned_area_summary", {"case_id": case_id, "month": month})
        summary = report.get("summary", {})
        if not summary.get("gate_passed"):
            return 1 + self._abstain(registry, [ReasonCode.INSUFFICIENT_VALID_DATA])
        claim = {
            "case_id": case_id,
            "month": month,
            "quantity": "burned_area_ha",
            "value": summary["primary_area_ha"],
            "statement": "Dispatcher value.",
        }
        self._call(registry, "submit_area_findings", {"claims": [claim]})
        return 2

    @staticmethod
    def _abstain(registry: ToolRegistry, codes: list[ReasonCode]) -> int:
        explanation = "Rule-based dispatcher: the question cannot be answered as asked."
        Dispatcher._call(
            registry, "declare_limitation", {"reasons": codes, "explanation": explanation}
        )
        return 1

    @staticmethod
    def _call(registry: ToolRegistry, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = registry.execute(name, json.dumps(arguments, default=str))
        return result.data or {}


def _claim(kind: str, region: str, window: dict[str, str], **fields: Any) -> dict[str, Any]:
    return {"kind": kind, "region": region, **window, "statement": "Dispatcher value.", **fields}
