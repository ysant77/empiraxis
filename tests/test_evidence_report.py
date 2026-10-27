"""W1: a burned-area run records the hash of every input it used, renders a report with
its checks and limitations, and replays offline. A changed input, method file or saved
verdict makes the replay fail."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from fake_client import ScriptedClient, call, say

from earthlab import cli
from earthlab.data.firms import detections_in_month
from earthlab.data.snapshot import SourceMismatchError
from earthlab.report.markdown import render_report
from earthlab.runtime import investigate, new_run_dir, open_workspace

ROOT = Path(__file__).resolve().parents[1]
CASE = "kalimantan-2015-burned-area"
METHOD = Path("config/methods/mcd64a1_burned_area.yaml")
SEPTEMBER = {
    "case_id": CASE,
    "month": "2015-09",
    "quantity": "burned_area_ha",
    "value": 77426.0,
    "statement": "Mapped burned area after quality checks.",
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A private copy of the pinned inputs, so a test can change them."""
    copy = tmp_path / "repo"
    for part in ("config/cases", "config/methods", "data/nea", "data/kalimantan-2015"):
        shutil.copytree(ROOT / part, copy / part)
    return copy


def run(repo: Path, steps: list[Any]) -> Path:
    run_dir = new_run_dir(repo / "runs")
    investigate("q", ScriptedClient(steps), open_workspace(repo / "data" / "nea"), run_dir)
    return run_dir


def area_run(repo: Path) -> Path:
    return run(
        repo,
        [
            call("burned_area_summary", case_id=CASE, month="2015-09"),
            call("submit_area_findings", claims=[SEPTEMBER]),
            say("The mapped burned area for the study box is in A1.1; it is not forest loss."),
        ],
    )


def abstained_run(repo: Path) -> Path:
    return run(
        repo,
        [
            call("burned_area_summary", case_id=CASE, month="2015-10"),
            call(
                "declare_limitation",
                reasons=["insufficient_valid_data"],
                explanation="Too little valid land data in the requested month.",
            ),
            say("The requested month fails the valid-data gate, so no area is reported."),
        ],
    )


def replay(repo: Path, run_dir: Path) -> int:
    return cli.main(["--data-dir", str(repo / "data" / "nea"), "replay", str(run_dir)])


def saved(run_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    return result


def test_area_run_records_every_input_hash(repo: Path) -> None:
    evidence = saved(area_run(repo))["evidence"]
    files = evidence["files"]
    assert str(METHOD) in files
    assert "config/cases/kalimantan-2015-burned-area.yaml" in files
    assert "data/kalimantan-2015/mcd64a1_2015_09.tif" in files
    assert "data/kalimantan-2015/firms_modis_sp_2015_09_2015_11.csv" in files
    (month,) = evidence["months"]
    assert month["case_id"] == CASE and month["month"] == "2015-09"
    assert month["check"]["passed"] and month["check"]["gate_ok"]
    assert month["firms_detections"] > 0


def test_abstained_run_records_the_month_it_consulted(repo: Path) -> None:
    result = saved(abstained_run(repo))
    assert result["status"] == "abstained"
    (month,) = result["evidence"]["months"]
    assert month["month"] == "2015-10" and not month["check"]["gate_ok"]


def test_replay_reproduces_an_area_run(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert replay(repo, area_run(repo)) == 0
    out = capsys.readouterr().out
    assert "area verdicts reproduced: 1/1" in out and "input hashes: all match" in out


def test_replay_fails_when_the_method_file_changes(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = area_run(repo)
    method = repo / METHOD
    method.write_text(
        method.read_text(encoding="utf-8").replace(
            "claim_relative_max: 0.001", "claim_relative_max: 0.5"
        ),
        encoding="utf-8",
    )
    assert replay(repo, run_dir) == 1
    assert f"changed: {METHOD}" in capsys.readouterr().out


def test_replay_fails_when_a_raster_changes(repo: Path) -> None:
    run_dir = area_run(repo)
    tif = repo / "data/kalimantan-2015/mcd64a1_2015_09.tif"
    tif.write_bytes(tif.read_bytes() + b"x")
    assert replay(repo, run_dir) == 1


def test_replay_fails_on_a_tampered_area_verdict(repo: Path) -> None:
    run_dir = area_run(repo)
    result = saved(run_dir)
    result["area_rounds"][0][0]["observed"] = 99999.0
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    assert replay(repo, run_dir) == 1


def test_replay_fails_closed_without_recorded_evidence(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = area_run(repo)
    result = saved(run_dir)
    del result["evidence"]
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    assert replay(repo, run_dir) == 1
    assert "input hashes: none recorded" in capsys.readouterr().out


def test_area_report_shows_checks_context_and_its_own_limitations(repo: Path) -> None:
    text = render_report(saved(area_run(repo)))
    assert "## Verifier checks (MCD64A1)" in text
    assert "| kalimantan-2015-burned-area | 2015-09 |" in text
    assert "not burned area" in text  # FIRMS is labelled as context only
    assert "500 m" in text and "not forest loss" in text.lower()
    assert "NEA regional aggregates" not in text  # PM2.5 limitations are not copied in
    assert "## Burned-area inputs" in text and str(METHOD) in text


def test_abstained_report_shows_the_declared_limitation(repo: Path) -> None:
    text = render_report(saved(abstained_run(repo)))
    assert "## Declared limitations" in text and "insufficient_valid_data" in text
    assert "valid fraction" in text
    assert "not reported (gate)" in text and "46118" not in text  # gated area stays hidden


@pytest.mark.parametrize("kind", ["area", "abstained", "pm25", "refused"])
def test_every_report_has_a_limitations_section(repo: Path, kind: str) -> None:
    steps: dict[str, list[Any]] = {
        "pm25": [say("No findings were made.")],
        "refused": [say("unused")],
    }
    if kind == "area":
        run_dir = area_run(repo)
    elif kind == "abstained":
        run_dir = abstained_run(repo)
    else:
        run_dir = run(repo, steps[kind])
    result = saved(run_dir)
    if kind == "refused":
        result["status"] = "refused"
    text = render_report(result)
    section = text.split("## Limitations", 1)
    assert len(section) == 2 and section[1].strip().startswith("- ")


def test_report_command_renders_a_saved_area_run(repo: Path) -> None:
    run_dir = area_run(repo)
    assert cli.main(["--data-dir", str(repo / "data" / "nea"), "report", str(run_dir)]) == 0
    text = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "## Verifier checks (MCD64A1)" in text and "pm25_hourly.png" not in text


def test_firms_counter_checks_the_hash_and_the_box(tmp_path: Path) -> None:
    folder = tmp_path / "f"
    shutil.copytree(ROOT / "data/kalimantan-2015", folder)
    manifest = "firms-modis-sp-kalimantan-2015.manifest.json"
    case = open_workspace(ROOT / "data" / "nea").cases
    assert case is not None
    box = case.get(CASE).case.area.bbox
    assert box is not None
    september = detections_in_month(folder, manifest, box, "2015-09")
    october = detections_in_month(folder, manifest, box, "2015-10")
    assert september > 0 and october > 0
    assert detections_in_month(folder, manifest, box, "2016-01") == 0
    csv = folder / "firms_modis_sp_2015_09_2015_11.csv"
    csv.write_text(csv.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(SourceMismatchError, match="sha256"):
        detections_in_month(folder, manifest, box, "2015-09")
