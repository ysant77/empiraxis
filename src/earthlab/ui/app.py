"""Streamlit demo: live investigation, saved-run replay, manual claim check and data QA.

Run with:  uv run --extra ui streamlit run src/earthlab/ui/app.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from earthlab.agent.budget import Budget
from earthlab.audit import RunTrace
from earthlab.cli import DEFAULT_WINDOW, write_report
from earthlab.contracts import Region, TimeWindow
from earthlab.data.quality import coverage_report
from earthlab.llm.client import build_client
from earthlab.llm.providers import load_providers
from earthlab.metrics import EarthlabMetrics
from earthlab.runtime import Workspace, investigate, new_run_dir, open_workspace
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
    st.write(result["answer"] or "_No final answer._")
    st.dataframe(_verdict_rows(result["rounds"]), use_container_width=True)
    chart = run_dir / "pm25_hourly.png"
    if chart.exists():
        st.image(str(chart))
    st.caption(
        f"Model {result['model']} via {result['provider']} (served: {result['served_model']}); "
        f"{result['turns']} turns, {result['tool_calls']} tool calls, {result['seconds']:.0f} s, "
        f"{result['prompt_tokens']} in / {result['completion_tokens']} out tokens. "
        f"Source sha256 {result['source']['sha256'][:16]}..."
    )


def tab_investigate() -> None:
    configs = {n: c for n, c in load_providers(PROVIDERS).items() if c.enabled}
    provider = st.selectbox("Meta model endpoint", list(configs))
    reasoning = st.selectbox("Reasoning strength", ["low", "medium", "high"])
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
        )
        write_report(run_dir, DATA_DIR)
        status.update(label="Investigation finished", state="complete")
    show_result(run_dir)


def tab_runs() -> None:
    runs = sorted((p for p in RUNS_DIR.glob("*") if (p / "result.json").exists()), reverse=True)
    if not runs:
        st.info("No saved runs yet.")
        return
    run_dir = st.selectbox("Saved run", runs, format_func=lambda p: p.name)
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
        "Evidence-first investigation of the 2015 Singapore haze with a Meta open-weight model. "
        "Research prototype: not health advice, not a forecast."
    )
    metrics()
    tabs = st.tabs(["Investigate", "Saved runs", "Verifier", "Data"])
    for tab, render in zip(tabs, (tab_investigate, tab_runs, tab_verifier, tab_data), strict=True):
        with tab:
            render()
    st.caption(f"Prometheus metrics: http://127.0.0.1:{METRICS_PORT}/metrics (local only)")


main()
