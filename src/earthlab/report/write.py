"""Write report.md (and its figures) for a saved run folder. No model is called."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from earthlab.contracts import TimeWindow
from earthlab.report.burn_map import burn_map
from earthlab.report.chart import hourly_chart
from earthlab.report.markdown import render_report
from earthlab.runtime import Workspace, open_workspace
from earthlab.science.burned_area import QaPolicy

DEFAULT_WINDOW = TimeWindow(start=datetime(2015, 9, 1), end=datetime(2015, 11, 1))


def write_report(run_dir: Path, workspace_dir: Path) -> Path:
    """report.md for a saved run; the PM2.5 chart only for runs that looked at PM2.5.

    A run that stopped at a declared limitation before any data read gets no chart.
    """
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    workspace = open_workspace(workspace_dir)
    chart = None
    if result["rounds"] or not (result.get("evidence") or result.get("limitations")):
        chart = "pm25_hourly.png"
        hourly_chart(workspace.dataset, DEFAULT_WINDOW, run_dir / chart)
    maps = _burn_maps(result.get("evidence"), workspace, run_dir)
    path = run_dir / "report.md"
    path.write_text(render_report(result, chart, maps), encoding="utf-8")
    return path


def _burn_maps(
    evidence: dict[str, Any] | None, workspace: Workspace, run_dir: Path
) -> dict[str, str]:
    """One primary-policy quick-look map per month the run read; months not read are skipped."""
    if not evidence or workspace.cases is None:
        return {}
    maps: dict[str, str] = {}
    for month in (m for m in evidence["months"] if "error" not in m):
        name = f"burn_map_{month['month']}.png"
        case_file = workspace.cases.get(month["case_id"])
        burn_map(case_file, workspace.cases.root, month["month"], QaPolicy.PRIMARY, run_dir / name)
        maps[month["month"]] = name
    return maps
