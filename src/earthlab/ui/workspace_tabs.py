"""The working product tabs: investigate, wildfire case, recorded runs, verifier and data.

These tabs hold the existing scientific features. Live investigation runs in operator
mode only; replay mode shows its controls disabled.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from earthlab.agent.area_findings import AreaClaim, verify_area_claim
from earthlab.contracts import Region, TimeWindow
from earthlab.data.mcd64a1 import read_manifest
from earthlab.data.quality import coverage_report
from earthlab.report.area_sections import AREA_LIMITATIONS
from earthlab.report.burn_map import burn_map
from earthlab.report.write import DEFAULT_WINDOW, write_report
from earthlab.science.burned_area import QaPolicy
from earthlab.tools.burned_area_tools import mcd64a1_asset_id, month_report
from earthlab.trace import RunTrace
from earthlab.ui import common
from earthlab.ui.live import run_live
from earthlab.verify.claims import Claim, ClaimKind

DEFAULT_QUESTION = (
    "During the September to October 2015 haze, which NEA region recorded the highest hourly "
    "PM2.5, and at what hour? A colleague claims the central region had the highest peak. "
    "Test that claim with the data."
)


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
        st.caption(common.PM25_CAPTION)
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
    maps = sorted(run_dir.glob("burn_map_*.png"))
    for image in maps:
        st.image(str(image), width=520)
    if maps:
        st.caption(common.MAP_CAPTION)
    elif result.get("area_findings") or result.get("limitations"):
        st.caption("Map unavailable: this run folder holds no burned-area map.")


@st.cache_data(show_spinner=False)
def _map_png(case_id: str, month: str, policy: str) -> bytes:
    library = common.workspace().cases
    assert library is not None
    out = common.RUNS_DIR / "ui" / f"burn_map_{case_id}_{month}_{policy}.png"
    return burn_map(library.get(case_id), library.root, month, QaPolicy(policy), out).read_bytes()


def tab_wildfire() -> None:
    """One month of a pinned case under a QA policy: tool value, verifier, gate, map."""
    library = common.workspace().cases
    cases = [] if library is None else [c for c in library.ids() if library.get(c).case.data_dir]
    if library is None or not cases:
        st.info("No burned-area case with pinned data.")
        return
    case_file = library.get(st.selectbox("Registered case", cases))
    folder = library.root / str(case_file.case.data_dir)
    manifest = read_manifest(folder / f"{mcd64a1_asset_id(case_file)}.manifest.json")
    cols = common.columns(2)
    month = cols[0].selectbox("Month (UTC)", [f["month"] for f in manifest["files"]])
    policy = QaPolicy(cols[1].selectbox("QA policy", [p.value for p in QaPolicy]))
    report = month_report(case_file, library.root, month, policy)
    s, c = report["summary"], report["check"]
    area = f"{s['primary_area_ha']:,.1f}" if s["gate_passed"] else "not reported (gate)"
    m = common.columns(4)
    m[0].metric("Mapped burned area (ha)", area)
    m[1].metric("Valid-land fraction", f"{s['valid_fraction']:.3f}")
    m[2].metric("Verifier checks", "pass" if c["passed"] else "FAIL")
    m[3].metric("Reporting gate", "pass" if c["gate_ok"] else "fail")
    st.image(_map_png(case_file.case.case_id, month, policy.value), width=560)
    st.caption(common.MAP_CAPTION)
    claimed = st.number_input("Claimed area (ha)", value=50000.0, step=100.0)
    if st.button("Check area claim"):
        raw = {"case_id": case_file.case.case_id, "month": month, "quantity": "burned_area_ha"}
        claim = AreaClaim.model_validate(
            {**raw, "value": claimed, "statement": "Manual check.", "qa_policy": policy}
        )
        st.json(verify_area_claim(claim, library).model_dump(mode="json", exclude={"claim"}))
    st.caption(" ".join(AREA_LIMITATIONS) + f" Source sha256 {s['source_sha256'][:16]}...")


def tab_investigate() -> None:
    if common.ui_mode() == "replay":
        st.caption(common.status_text("unavailable", "Live investigation is off in replay mode."))
        st.text_area("Research question", DEFAULT_QUESTION, height=110, disabled=True)
        st.button("Run investigation", type="primary", disabled=True)
        st.write(
            "A local operator can start the app with EARTHLAB_UI_MODE=operator to run a live "
            "investigation on a local Meta model. The public replay never calls a model."
        )
        return
    question = st.text_area("Research question", DEFAULT_QUESTION, height=110)
    run_dir = run_live(question)
    if run_dir is not None:
        write_report(run_dir, common.DATA_DIR)
        show_result(run_dir)


def _run_choices() -> list[tuple[str, Path | None]]:
    """Replay runs by name; operator mode adds saved local runs."""
    choices: list[tuple[str, Path | None]] = [(f"replay/{n}", None) for n in common.replay_names()]
    if common.ui_mode() == "operator" and common.RUNS_DIR.is_dir():
        found = sorted(
            common.RUNS_DIR.rglob("result.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        choices += [(str(p.parent.relative_to(common.RUNS_DIR)), p.parent) for p in found[:200]]
    return choices


def tab_runs() -> None:
    choices = _run_choices()
    if not choices:
        st.info("No recorded runs are available.")
        return
    labels = [c[0] for c in choices]
    picked = st.selectbox("Recorded run", labels)
    local = dict(choices)[picked]
    if local is None:
        run_dir, events, error = common.load_replay(picked.removeprefix("replay/"))
        if run_dir is None or events is None:
            st.error(f"Run not shown. Integrity check failed: {error}")
            return
        records = events.trace_records
        split = common.replay_entry(events.run_id).get("split", "unknown")
        st.caption(f"Split: {split}. Provenance: {common.replay_provenance()}")
    else:
        run_dir, records = local, RunTrace(local / "trace.jsonl").verify()
    st.success(f"Trace hash chain intact ({records} records).")
    show_result(run_dir)


def tab_verifier() -> None:
    st.write("Check one claim against the raw source, with no model involved.")
    cols = common.columns(3)
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
        result = common.workspace().verifier.verify(Claim.model_validate(payload))
        common.record_verification(result.check.value, result.verdict.value)
        st.json(result.model_dump(mode="json", exclude={"claim"}))


def tab_data() -> None:
    start = st.date_input("Start", DEFAULT_WINDOW.start.date())
    end = st.date_input("End (excluded)", DEFAULT_WINDOW.end.date())
    window = TimeWindow(
        start=datetime.combine(start, datetime.min.time()),
        end=datetime.combine(end, datetime.min.time()),
    )
    report = coverage_report(common.workspace().dataset, window)
    st.dataframe([r.model_dump(mode="json", exclude={"gaps"}) for r in report.regions])
    st.write("File-level issues found at load:", report.file_issue_counts)
    st.caption(common.workspace().snapshot.attribution)
    st.caption(common.PM25_CAPTION)
