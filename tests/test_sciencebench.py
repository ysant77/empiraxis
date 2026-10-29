"""Acceptance tests for the ScienceBench harness (PR-1): scenarios, scoring, arm A, arm B
plumbing, abstention and the assess_case tool. Fake model scripts only; no live model."""

from __future__ import annotations

import inspect
import itertools
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say
from pydantic import ValidationError

from earthlab import cli
from earthlab.agent.budget import Budget
from earthlab.agent.findings import FindingsLedger
from earthlab.agent.limitations import ReasonCode
from earthlab.agent.loop import RunStatus
from earthlab.bench.dispatcher import Dispatcher, parse_windows
from earthlab.bench.runner import run_bench, run_metadata
from earthlab.bench.scenarios import Outcome, Scenario, load_scenarios, score
from earthlab.contracts import MAX_WINDOW_DAYS
from earthlab.runtime import Workspace, build_registry, investigate, new_run_dir, open_workspace
from earthlab.verify.claims import Check, Claim, Verdict, VerificationResult

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = load_scenarios(ROOT / "evals" / "sciencebench_dev_v1.yaml")
BY_ID = {s.id: s for s in SCENARIOS}
HAZE = {"start": "2015-09-01T00:00", "end": "2015-11-01T00:00"}
PEAK = {**HAZE, "kind": "peak_region", "region": "west", "value": 471, "statement": "Seen."}


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def supported(raw: dict[str, Any]) -> VerificationResult:
    claim = Claim.model_validate(raw)
    return VerificationResult(claim=claim, verdict=Verdict.SUPPORTED, check=Check.VALUE, reason="")


def test_scenario_file_is_complete_and_honest() -> None:
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids)) == 24 and {f"SB-{i:02d}" for i in range(1, 21)} <= set(ids)
    ready = {s.id for s in SCENARIOS if s.status == "ready"}
    assert ready == {
        "SB-01",
        "SB-02",
        "SB-02b",
        "SB-03",
        "SB-04",
        "SB-05",
        "SB-05b",
        "SB-05c",
        "SB-05d",
        "SB-06",
        "SB-07",
        "SB-08",
        "SB-16",
    }
    assert all(s.blocked_reason for s in SCENARIOS if s.status == "blocked_unrun")
    text = (ROOT / "evals" / "sciencebench_dev_v1.yaml").read_text(encoding="utf-8")
    assert "value:" not in text  # no numeric gold answers are stored


def test_scenario_validation_fails_closed() -> None:
    base = {"id": "SB-99", "priority": "P0", "title": "t", "question": "A question here?"}
    with pytest.raises(ValidationError, match="blocked_reason"):
        Scenario.model_validate({**base, "status": "blocked_unrun", "expected": "abstain"})
    with pytest.raises(ValidationError, match="needs requirements"):
        Scenario.model_validate({**base, "status": "ready", "expected": "verified_claims"})
    with pytest.raises(ValidationError, match="needs reason_codes"):
        Scenario.model_validate({**base, "status": "ready", "expected": "abstain"})


def test_blocked_scenarios_are_listed_never_run(workspace: Workspace, tmp_path: Path) -> None:
    summary = run_bench(SCENARIOS, ["A"], workspace, tmp_path, repo=ROOT)
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text().splitlines()]
    blocked = {s.id for s in SCENARIOS if s.status == "blocked_unrun"}
    assert not blocked & {r["scenario_id"] for r in rows}
    assert set(summary["blocked_unrun"]) == blocked and len(blocked) == 11
    assert summary["arms"]["A"]["runs"] == 13 and summary["arms"]["A"]["false_verified"] == 0
    assert rows[0]["meta"]["data_sha256"] == workspace.snapshot.sha256


def test_arm_a_reads_only_the_question(workspace: Workspace) -> None:
    assert list(inspect.signature(Dispatcher.run).parameters) == ["self", "question"]
    import earthlab.bench.dispatcher as module

    source = inspect.getsource(module)
    assert (
        ".requirements" not in source
        and ".expected" not in source
        and ".reason_codes" not in source
    )
    assert "import Outcome\n" in source  # the only thing it takes from the scenario module


@pytest.mark.parametrize(
    ("codes", "passed"), [([ReasonCode.OUT_OF_SCOPE], False), ([ReasonCode.HOTSPOT_NOT_AREA], True)]
)
def test_abstention_needs_the_named_reason(codes: list[ReasonCode], passed: bool) -> None:
    result = score(BY_ID["SB-06"], "B", 0, Outcome(status="abstained", reason_codes=codes))
    assert result.passed is passed


def test_claims_in_an_abstain_scenario_count_as_false_verified() -> None:
    outcome = Outcome(
        status="abstained", reason_codes=[ReasonCode.HOTSPOT_NOT_AREA], supported=[supported(PEAK)]
    )
    result = score(BY_ID["SB-06"], "B", 0, outcome)
    assert not result.passed and result.false_verified == 1
    verified = score(BY_ID["SB-16"], "B", 0, Outcome(status="verified"))
    assert not verified.passed and verified.false_verified == 1
    allowed = Outcome(
        status="abstained",
        reason_codes=[ReasonCode.CAUSATION_NOT_IDENTIFIABLE],
        supported=[supported(PEAK)],
    )
    assert score(BY_ID["SB-04"], "B", 0, allowed).passed  # SB-04 allows observed claims


def test_needs_input_scenario(workspace: Workspace, tmp_path: Path) -> None:
    sb02b = BY_ID["SB-02b"]
    assert score(sb02b, "A", 0, Dispatcher(workspace).run(sb02b.question)).passed
    guessed = {
        **HAZE,
        "kind": "hours_above",
        "region": "west",
        "value": 1,
        "threshold": 150,
        "statement": "Guess.",
    }
    outcome = Outcome(status="verified", supported=[supported(guessed)])
    assert not score(sb02b, "B", 0, outcome).passed


def test_both_arms_score_the_same_for_the_same_actions(
    workspace: Workspace, tmp_path: Path
) -> None:
    sb01 = BY_ID["SB-01"]
    client = ScriptedClient(
        [
            call("rank_regions", **HAZE, statistic="max"),
            call("submit_findings", claims=[PEAK]),
            say("West had the highest hourly value (R1.1)."),
        ]
    )
    summary = run_bench([sb01], ["A", "B"], workspace, tmp_path, repo=ROOT, client=client)
    assert (
        summary["arms"]["A"]["per_scenario"]
        == summary["arms"]["B"]["per_scenario"]
        == {"SB-01": "1/1"}
    )


def test_agent_abstains_through_declare_limitation(workspace: Workspace, tmp_path: Path) -> None:
    sb16 = BY_ID["SB-16"]
    reasons = {
        "reasons": ["land_surface_temperature_is_not_air_temperature"],
        "explanation": "Satellite skin temperature is not a near-surface air temperature.",
    }
    client = ScriptedClient(
        [
            call("declare_limitation", **reasons),
            say("Land-surface temperature is not air temperature."),
        ]
    )
    run_dir = new_run_dir(tmp_path)
    result = investigate(sb16.question, client, workspace, run_dir)
    assert result.status is RunStatus.ABSTAINED and result.limitations[0].reasons[
        0
    ].value.startswith("land")
    assert client.requests[-1]["tool_choice"] == "none"
    payload = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert payload["limitations"][0]["reasons"] == reasons["reasons"]


def test_abstention_text_is_still_checked(workspace: Workspace, tmp_path: Path) -> None:
    reasons = {
        "reasons": ["hotspot_count_is_not_burned_area"],
        "explanation": "Counts are not area.",
    }
    client = ScriptedClient(
        [
            call("declare_limitation", **reasons),
            say("No, 500 is not hectares."),
            say("No, 500 is not hectares."),
        ]
    )
    result = investigate("q", client, workspace, new_run_dir(tmp_path))
    assert (
        result.status is RunStatus.ANSWER_UNVERIFIED
        and "numbers in the text" in result.answer_issues[0]
    )


def test_assess_case_reports_the_exact_blockers(workspace: Workspace) -> None:
    registry = build_registry(workspace, FindingsLedger())
    report = registry.execute(
        "assess_case", json.dumps({"case_id": "uttarakhand-2024-burned-area"})
    )
    assert report.data is not None and report.data["status"] == "blocked"
    assert "mcd64a1-061-uttarakhand-2024 is unavailable for this case" in report.data["reasons"]
    unknown = registry.execute("assess_case", json.dumps({"case_id": "mars"}))
    assert unknown.error is not None and "known:" in unknown.error


def test_windows_from_text() -> None:
    assert parse_windows("in September-October 2015") == [
        (datetime(2015, 9, 1), datetime(2015, 11, 1))
    ]
    assert parse_windows("from 2015-09-01 to 2015-10-01") == [
        (datetime(2015, 9, 1), datetime(2015, 10, 1))
    ]
    year = parse_windows("peaked at 999 in 2015")
    assert year[0][0] == datetime(2015, 1, 1) and year[-1][1] == datetime(2016, 1, 1)
    assert all(b - a <= timedelta(days=MAX_WINDOW_DAYS) for a, b in year)
    assert all(a[1] == b[0] for a, b in itertools.pairwise(year))
    assert parse_windows("no dates here") == []


def test_metadata_and_cli(
    workspace: Workspace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    meta = run_metadata(ROOT, workspace, None, Budget())
    assert meta["code_revision"] and "nea-2015-haze.yaml" in meta["case_files_sha256"]
    code = cli.main(
        [
            "--data-dir",
            str(REPO_DATA),
            "bench",
            "--arms",
            "A",
            "--only",
            "SB-01,SB-05",
            "--runs-dir",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0 and "SB-01 [A] r0 passed=True" in out and '"SB-05"' in out
    with pytest.raises(SystemExit):
        cli.main(["bench", "--arms", "Z"])
    with pytest.raises(ValueError, match="arm B without a model client"):
        run_bench(SCENARIOS, ["B"], workspace, tmp_path / "b", repo=ROOT)


@pytest.mark.parametrize(
    "text",
    [
        # Observed in the live ScienceBench arm B run of 2026-10-27 (SB-08).
        "The case is blocked because the required burned-area dataset is unavailable.",
        "The study is blocked due to data unavailability and a missing approval.",
        # Withheld in the live W2 run of 2026-10-27 (SB-05c, repeat 2).
        "Because the October value is insufficient, the comparison cannot be made as asked.",
        "No comparison is made because one month fails the valid-data gate.",
    ],
)
def test_availability_reasons_are_not_causal_claims(text: str) -> None:
    from earthlab.safety.scope import answer_out_of_scope

    assert answer_out_of_scope(text) is None
    assert answer_out_of_scope("The haze was caused by fires in Kalimantan.") is not None
    assert answer_out_of_scope("Readings rose because smoke arrived from the south.") is not None


def test_identifiers_and_product_names_are_not_numbers() -> None:
    from earthlab.verify.answer_audit import text_numbers

    # Observed live: "mcd64a1_burned_area" and "NEA historical 1-hour PM2.5" (SB-08, SB-03).
    assert text_numbers("The mcd64a1_burned_area method and the NEA 1-hour PM2.5 record.") == []
    assert text_numbers("It peaked in 2015 at 471.") == ["2015", "471"]


class _Boom(ScriptedClient):
    """A client whose every call raises an unexpected error."""

    def chat(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("unexpected failure")


def test_a_crash_is_an_error_row_and_the_run_continues(
    workspace: Workspace, tmp_path: Path
) -> None:
    """A3/A4: an exception is scored as a failure; every row and the summary are written."""
    picked = [BY_ID["SB-06"], BY_ID["SB-16"]]
    summary = run_bench(
        picked, ["A", "B"], workspace, tmp_path, repo=ROOT, client=_Boom([]), repeats=2
    )
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text().splitlines()]
    errors = [r for r in rows if r["arm"] == "B"]
    assert len(rows) == 8 and len(errors) == 4
    assert all(r["outcome"]["status"] == "error" and not r["passed"] for r in errors)
    assert "RuntimeError" in errors[0]["outcome"]["detail"]["error"]
    assert summary["rows_expected"] == summary["rows_written"] == 8 and summary["complete"]
    assert summary["arms"]["B"]["errors"] == 4
