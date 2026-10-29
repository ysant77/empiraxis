"""Streamlit demo: live investigation, wildfire case view, saved runs, claim check, data QA.

Run with:  uv run --extra ui streamlit run src/earthlab/ui/app.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from earthlab.agent.area_findings import AreaClaim, verify_area_claim
from earthlab.agent.budget import Budget
from earthlab.contracts import Region, TimeWindow
from earthlab.data.mcd64a1 import read_manifest
from earthlab.data.quality import coverage_report
from earthlab.llm.client import build_client
from earthlab.llm.providers import load_providers
from earthlab.llm.raw import RawCompletionClient
from earthlab.metrics import EarthlabMetrics
from earthlab.report.area_sections import AREA_LIMITATIONS
from earthlab.report.burn_map import burn_map
from earthlab.report.write import DEFAULT_WINDOW, write_report
from earthlab.runtime import Workspace, investigate, new_run_dir, open_workspace
from earthlab.safety.llama_guard import LlamaGuard
from earthlab.science.burned_area import QaPolicy
from earthlab.tools.burned_area_tools import mcd64a1_asset_id, month_report
from earthlab.trace import RunTrace
from earthlab.verify.claims import Claim, ClaimKind

DATA_DIR = Path("data/nea")
RUNS_DIR = Path("runs")
PROVIDERS = Path("config/providers.yaml")
METRICS_PORT = int(os.environ.get("EARTHLAB_METRICS_PORT", "9464"))
DEFAULT_QUESTION = (
    "During the September to October 2015 haze, which NEA region recorded the highest hourly "
    "PM2.5, and at what hour? A colleague claims the central region had the highest peak. "
    "Test that claim with the data."
)


@st.cache_resource
def workspace() -> Workspace:
    return open_workspace(DATA_DIR)


@st.cache_resource
def metrics() -> EarthlabMetrics:
    shared = EarthlabMetrics()
    shared.serve(METRICS_PORT)
    return shared


def _verdict_rows(rounds: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [
        {
            "round": i + 1,
            "kind": r["claim"]["kind"],
            "region": r["claim"]["region"],
            "claimed": r["claim"].get("value"),
            "observed": r.get("observed"),
            "verdict": r["verdict"],
            "reason": r["reason"],
        }
        for i, rnd in enumerate(rounds)
        for r in rnd
    ]


def show_result(run_dir: Path) -> None:
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    st.subheader(f"Status: {result['status']}")
    findings = [f for f in result.get("findings", []) if f["verdict"] == "supported"]
    if findings or result["rounds"]:
        st.markdown("**Findings (verified claims)**")
        st.dataframe(findings, use_container_width=True)
    st.markdown("**Interpretation (model text)**")
    for issue in result.get("answer_issues", []):
        st.error(f"Not verified: {issue}")
    st.write(result["answer"] or "_No final answer._")
    if result["rounds"]:
        st.dataframe(_verdict_rows(result["rounds"]), use_container_width=True)
    _show_area(result, run_dir)
    chart = run_dir / "pm25_hourly.png"
    if chart.exists():
        st.image(str(chart))
    st.caption(
        f"Model {result['model']} via {result['provider']} (served: {result['served_model']}); "
        f"{result['turns']} turns, {result['tool_calls']} tool calls, {result['seconds']:.0f} s, "
        f"{result['prompt_tokens']} in / {result['completion_tokens']} out tokens. "
        f"Source sha256 {result['source']['sha256'][:16]}..."
    )


def _show_area(result: dict[str, Any], run_dir: Path) -> None:
    """Burned-area claims with every verdict, declared limitations and the run's maps."""
    if result.get("area_findings"):
        st.markdown("**Burned-area claims (independent verifier)**")
        st.dataframe(result["area_findings"], use_container_width=True)
    for entry in result.get("limitations", []):
        st.warning(f"Declared limitation {', '.join(entry['reasons'])}: {entry['explanation']}")
    for image in sorted(run_dir.glob("burn_map_*.png")):
        st.image(str(image), width=520)


@st.cache_data(show_spinner=False)
def _map_png(case_id: str, month: str, policy: str) -> bytes:
    library = workspace().cases
    assert library is not None
    out = RUNS_DIR / "ui" / f"burn_map_{case_id}_{month}_{policy}.png"
    return burn_map(library.get(case_id), library.root, month, QaPolicy(policy), out).read_bytes()


def tab_wildfire() -> None:
    """One month of a pinned case under a QA policy: tool value, verifier, gate, map."""
    library = workspace().cases
    cases = [] if library is None else [c for c in library.ids() if library.get(c).case.data_dir]
    if library is None or not cases:
        st.info("No burned-area case with pinned data.")
        return
    case_file = library.get(st.selectbox("Registered case", cases))
    folder = library.root / str(case_file.case.data_dir)
    manifest = read_manifest(folder / f"{mcd64a1_asset_id(case_file)}.manifest.json")
    cols = st.columns(2)
    month = cols[0].selectbox("Month (UTC)", [f["month"] for f in manifest["files"]])
    policy = QaPolicy(cols[1].selectbox("QA policy", [p.value for p in QaPolicy]))
    report = month_report(case_file, library.root, month, policy)
    s, c = report["summary"], report["check"]
    area = f"{s['primary_area_ha']:,.1f}" if s["gate_passed"] else "not reported (gate)"
    m = st.columns(4)
    m[0].metric("Mapped burned area (ha)", area)
    m[1].metric("Valid-land fraction", f"{s['valid_fraction']:.3f}")
    m[2].metric("Verifier checks", "pass" if c["passed"] else "FAIL")
    m[3].metric("Reporting gate", "pass" if c["gate_ok"] else "fail")
    st.image(_map_png(case_file.case.case_id, month, policy.value), width=560)
    claimed = st.number_input("Claimed area (ha)", value=50000.0, step=100.0)
    if st.button("Check area claim"):
        raw = {"case_id": case_file.case.case_id, "month": month, "quantity": "burned_area_ha"}
        claim = AreaClaim.model_validate(
            {**raw, "value": claimed, "statement": "Manual check.", "qa_policy": policy}
        )
        st.json(verify_area_claim(claim, library).model_dump(mode="json", exclude={"claim"}))
    st.caption(" ".join(AREA_LIMITATIONS) + f" Source sha256 {s['source_sha256'][:16]}...")


def tab_investigate() -> None:
    configs = {n: c for n, c in load_providers(PROVIDERS).items() if c.enabled}
    planners = [n for n, c in configs.items() if "guard" not in c.logical_model]
    provider = st.selectbox("Meta model endpoint", planners)
    reasoning = st.selectbox("Reasoning strength", ["low", "medium", "high"])
    guards = [n for n, c in configs.items() if "guard" in c.logical_model]
    guard_name = st.selectbox("Safety model (Meta Llama Guard)", [*guards, "none"])
    question = st.text_area("Research question", DEFAULT_QUESTION, height=110)
    if not st.button("Run investigation", type="primary"):
        return
    run_dir = new_run_dir(RUNS_DIR)
    with st.status("Investigating with a Meta open-weight model...", expanded=True) as status:

        def listener(record: dict[str, Any]) -> None:
            data = record["data"]
            if record["event"] == "model_turn":
                names = ", ".join(c["name"] for c in data["tool_calls"]) or "final answer"
                status.write(f"Turn {data['turn']}: model chose **{names}**")
            elif record["event"] == "safety_check":
                verdict = "allowed" if data["allowed"] else f"blocked ({data['reason']})"
                status.write(f"Safety check on the {data['stage']}: {verdict}")
            elif record["event"] == "tool_result":
                status.write(f"`{data['name']}` -> {data['outcome']}")

        investigate(
            question,
            build_client(configs[provider]),
            workspace(),
            run_dir,
            metrics=metrics(),
            budget=Budget(),
            reasoning=reasoning,
            listener=listener,
            guard=None
            if guard_name == "none"
            else LlamaGuard(
                RawCompletionClient(configs[guard_name]), configs[guard_name].logical_model
            ),
        )
        write_report(run_dir, DATA_DIR)
        status.update(label="Investigation finished", state="complete")
    show_result(run_dir)


def tab_runs() -> None:
    found = sorted(RUNS_DIR.rglob("result.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    runs = [p.parent for p in found[:200]]  # investigations, bench and demo runs
    if not runs:
        st.info("No saved runs yet.")
        return
    run_dir = st.selectbox("Saved run", runs, format_func=lambda p: str(p.relative_to(RUNS_DIR)))
    records = RunTrace(run_dir / "trace.jsonl").verify()
    st.success(f"Trace hash chain intact ({records} records).")
    show_result(run_dir)


def tab_verifier() -> None:
    st.write("Check one claim against the raw source, with no model involved.")
    cols = st.columns(3)
    kind = cols[0].selectbox("Claim kind", [k.value for k in ClaimKind])
    region = cols[1].selectbox("Region", [r.value for r in Region])
    value = cols[2].number_input("Value", value=471.0)
    threshold = st.number_input("Threshold (hours_above only)", value=200.0)
    statement = st.text_input("Statement", "West recorded the highest hourly value.")
    if st.button("Verify claim"):
        payload: dict[str, Any] = {
            "kind": kind,
            "region": region,
            "start": DEFAULT_WINDOW.start,
            "end": DEFAULT_WINDOW.end,
            "statement": statement,
            "value": value,
        }
        if kind == ClaimKind.HOURS_ABOVE:
            payload["threshold"] = threshold
        result = workspace().verifier.verify(Claim.model_validate(payload))
        metrics().record_verification(result.check.value, result.verdict.value)
        st.json(result.model_dump(mode="json", exclude={"claim"}))


def tab_data() -> None:
    start = st.date_input("Start", DEFAULT_WINDOW.start.date())
    end = st.date_input("End (excluded)", DEFAULT_WINDOW.end.date())
    window = TimeWindow(
        start=datetime.combine(start, datetime.min.time()),
        end=datetime.combine(end, datetime.min.time()),
    )
    report = coverage_report(workspace().dataset, window)
    st.dataframe([r.model_dump(mode="json", exclude={"gaps"}) for r in report.regions])
    st.write("File-level issues found at load:", report.file_issue_counts)
    st.caption(workspace().snapshot.attribution)


def main() -> None:
    st.set_page_config(page_title="Axiom EarthLab", layout="wide")
    st.title("Axiom EarthLab")
    st.caption(
        "Evidence-first investigation of the 2015 haze and Kalimantan burned area with a Meta "
        "open-weight model. "
        "Research prototype: not health advice, not a forecast."
    )
    metrics()
    names = ["Investigate", "Wildfire case", "Saved runs", "Verifier", "Data"]
    renders = (tab_investigate, tab_wildfire, tab_runs, tab_verifier, tab_data)
    for tab, render in zip(st.tabs(names), renders, strict=True):
        with tab:
            render()
    st.caption(f"Prometheus metrics: http://127.0.0.1:{METRICS_PORT}/metrics (local only)")


main()
