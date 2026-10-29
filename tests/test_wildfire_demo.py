"""W2b: burned-area map, report figure, the scripted wildfire demo and its CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_client import ScriptedClient, call, say

from earthlab import cli
from earthlab.cases.loader import load_case
from earthlab.demo import DEMO_IDS, run_demo
from earthlab.report.burn_map import burn_map, burned_points
from earthlab.report.write import write_report
from earthlab.runtime import Workspace, investigate, new_run_dir, open_workspace
from earthlab.science.burned_area import QaPolicy
from earthlab.tools.burned_area_tools import month_report

ROOT = Path(__file__).resolve().parents[1]
NEA = ROOT / "data" / "nea"
CASE = "kalimantan-2015-burned-area"
CASE_FILE = ROOT / "config" / "cases" / f"{CASE}.yaml"
SEPTEMBER = {
    "case_id": CASE,
    "month": "2015-09",
    "quantity": "burned_area_ha",
    "value": 77426.0,
    "statement": "Mapped burned area after quality checks.",
}


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(NEA)


def area_steps() -> list[Any]:
    return [
        call("burned_area_summary", case_id=CASE, month="2015-09"),
        call("submit_area_findings", claims=[SEPTEMBER]),
        say("The mapped burned area for the study box is in A1.1; it is not forest loss."),
    ]


def hotspot_steps() -> list[Any]:
    return [
        call(
            "declare_limitation",
            reasons=["hotspot_count_is_not_burned_area"],
            explanation="A hotspot is a thermal detection, not an area of burned land.",
        ),
        say("Hotspot detections cannot be converted into burned area."),
    ]


@pytest.mark.parametrize("policy", [QaPolicy.PRIMARY, QaPolicy.STRICT])
def test_map_points_match_the_tool_count(policy: QaPolicy) -> None:
    case = load_case(CASE_FILE, ROOT)
    points = burned_points(case, ROOT, "2015-09", policy)
    summary = month_report(case, ROOT, "2015-09", policy)["summary"]
    assert len(points.burned_lon) == summary["burned_pixels"]
    assert len(points.firms_lon) > 0  # FIRMS detections in the box that month


def test_burn_map_writes_a_labelled_png(tmp_path: Path) -> None:
    out = burn_map(
        load_case(CASE_FILE, ROOT), ROOT, "2015-10", QaPolicy.PRIMARY, tmp_path / "m.png"
    )
    assert out.read_bytes()[:4] == b"\x89PNG" and out.stat().st_size > 5000


def test_area_report_embeds_the_map(workspace: Workspace, tmp_path: Path) -> None:
    run_dir = new_run_dir(tmp_path)
    investigate("q", ScriptedClient(area_steps()), workspace, run_dir)
    text = write_report(run_dir, NEA).read_text(encoding="utf-8")
    assert "![Burned-area map 2015-09](burn_map_2015-09.png)" in text
    assert (run_dir / "burn_map_2015-09.png").stat().st_size > 5000
    assert "pm25_hourly.png" not in text


def test_demo_runs_each_question_writes_a_report_and_replays(
    workspace: Workspace, tmp_path: Path
) -> None:
    scripts = iter([area_steps(), hotspot_steps()])
    rows = run_demo(
        ["SB-05", "SB-06"],
        lambda: ScriptedClient(next(scripts)),
        workspace,
        tmp_path / "runs",
        NEA,
    )
    assert [(r["id"], r["status"], r["replay_ok"]) for r in rows] == [
        ("SB-05", "verified", True),
        ("SB-06", "abstained", True),
    ]
    assert all(Path(r["report"]).is_file() for r in rows)
    summary = json.loads((tmp_path / "runs" / "demo_summary.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in summary["rows"]] == ["SB-05", "SB-06"]


def test_demo_ids_are_ready_wildfire_scenarios() -> None:
    from earthlab.bench.scenarios import load_scenarios

    ready = {
        s.id
        for s in load_scenarios(ROOT / "evals" / "sciencebench_dev_v1.yaml")
        if s.status == "ready"
    }
    assert set(DEMO_IDS) <= ready and "SB-07" in DEMO_IDS
    with pytest.raises(ValueError, match="unknown"):
        run_demo(["SB-99"], lambda: ScriptedClient([]), open_workspace(NEA), Path("x"), NEA)


def test_demo_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "build_client", lambda config: ScriptedClient(hotspot_steps()))
    code = cli.main(["demo", "--only", "SB-06", "--guard", "none", "--runs-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0 and "SB-06" in out and "abstained" in out and "replay ok" in out
