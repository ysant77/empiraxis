"""Typed burned-area claims: the independent verifier's verdicts, the agent loop, the
report, the interpretation check and ScienceBench scoring (SB-05, SB-05b)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_client import ScriptedClient, call, say

from earthlab.agent.area_findings import AreaClaim, verify_area_claim
from earthlab.agent.loop import RunStatus
from earthlab.bench.runner import run_bench
from earthlab.bench.scenarios import Outcome, load_scenarios, score
from earthlab.cases.tools import CaseLibrary
from earthlab.report.markdown import render_report
from earthlab.runtime import Workspace, investigate, new_run_dir, open_workspace, result_payload
from earthlab.tools.burned_area_tools import month_report
from earthlab.verify.claims import Check, Verdict

ROOT = Path(__file__).resolve().parents[1]
CASE = "kalimantan-2015-burned-area"
SCENARIOS = {s.id: s for s in load_scenarios(ROOT / "evals" / "sciencebench_dev_v1.yaml")}


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(ROOT / "data" / "nea")


@pytest.fixture(scope="module")
def september_ha(workspace: Workspace) -> float:
    assert workspace.cases is not None
    value: float = month_report(workspace.cases.get(CASE), ROOT, "2015-09")["summary"][
        "primary_area_ha"
    ]
    return value


def claim(month: str, value: float, **changes: Any) -> dict[str, Any]:
    return {
        "case_id": CASE,
        "month": month,
        "quantity": "burned_area_ha",
        "value": value,
        "statement": "Mapped burned area after quality checks.",
        **changes,
    }


def verdict(library: CaseLibrary, raw: dict[str, Any]) -> Verdict:
    return verify_area_claim(AreaClaim.model_validate(raw), library).verdict


def test_verifier_verdicts(workspace: Workspace, september_ha: float) -> None:
    lib = workspace.cases
    assert lib is not None
    assert verdict(lib, claim("2015-09", september_ha)) is Verdict.SUPPORTED
    assert verdict(lib, claim("2015-09", september_ha * 1.0005)) is Verdict.SUPPORTED  # within 0.1%
    assert verdict(lib, claim("2015-09", september_ha * 1.01)) is Verdict.CONTRADICTED
    assert verdict(lib, claim("2015-10", 46118.0)) is Verdict.INSUFFICIENT_DATA  # quality gate
    assert verdict(lib, claim("2015-11", 1.0)) is Verdict.INSUFFICIENT_DATA  # not pinned
    assert (
        verdict(lib, claim("2015-09", 1.0, case_id="uttarakhand-2024-burned-area"))
        is Verdict.INSUFFICIENT_DATA
    )
    fraction = claim("2015-09", 0.970, quantity="valid_fraction")
    assert verdict(lib, fraction) is Verdict.SUPPORTED
    assert verdict(lib, {**fraction, "value": 0.9}) is Verdict.CONTRADICTED
    causal = verify_area_claim(
        AreaClaim.model_validate(
            claim("2015-09", september_ha, statement="Plantation clearing caused this burned area.")
        ),
        lib,
    )
    assert causal.verdict is Verdict.UNSUPPORTED and causal.check is Check.LANGUAGE


def test_agent_verifies_a_burned_area_claim(
    workspace: Workspace, september_ha: float, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            call("burned_area_summary", case_id=CASE, month="2015-09"),
            call("submit_area_findings", claims=[claim("2015-09", september_ha)]),
            say("The mapped burned area for the study box is in A1.1; it is not forest loss."),
        ]
    )
    run_dir = new_run_dir(tmp_path)
    result = investigate(SCENARIOS["SB-05"].question, client, workspace, run_dir)
    assert result.status is RunStatus.VERIFIED and result.submissions == 1
    payload = result_payload("q", result, workspace.snapshot)
    assert (
        payload["area_findings"][0]["id"] == "A1.1"
        and payload["area_findings"][0]["verdict"] == "supported"
    )
    report = render_report(payload)
    assert (
        "## Burned-area findings" in report
        and "| A1.1 | kalimantan-2015-burned-area | 2015-09 |" in report
    )


def test_unsupported_area_claims_do_not_verify(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            call("submit_area_findings", claims=[claim("2015-10", 46118.0)]),
            say("October is in A1.1."),
            say("October is in A1.1."),
        ]
    )
    result = investigate("q", client, workspace, new_run_dir(tmp_path))
    assert result.status is not RunStatus.VERIFIED
    assert (
        any("A1.1 is not a supported finding" in i for i in result.answer_issues)
        or not result.answer
    )


def test_bench_scores_area_scenarios(
    workspace: Workspace, tmp_path: Path, september_ha: float
) -> None:
    summary = run_bench(
        [SCENARIOS["SB-05"], SCENARIOS["SB-05b"]], ["A"], workspace, tmp_path, repo=ROOT
    )
    assert summary["arms"]["A"]["per_scenario"] == {"SB-05": "1/1", "SB-05b": "1/1"}
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text().splitlines()]
    assert rows[0]["outcome"]["area_supported"][0]["claim"]["month"] == "2015-09"
    assert not score(SCENARIOS["SB-05"], "B", 0, Outcome(status="verified", seconds=1.0)).passed
