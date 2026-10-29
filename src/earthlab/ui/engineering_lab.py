"""Geospatial Engineering Lab: method choice, data QA and benchmark status, read-only.

Every number here comes from pinned data, committed config or a recorded development
bench summary. No model has been trained, so no training curve or model score is shown.
The official held-out panel states its run status only, until the owner supplies results.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st
import yaml

from earthlab.events.bench import DEV_LABEL, DevBench, find_dev_benches
from earthlab.science.burned_area import QaPolicy
from earthlab.tools.burned_area_tools import month_report
from earthlab.ui import common

METHOD_FILE = Path("config/methods/mcd64a1_burned_area.yaml")
PROTOCOL_FILE = Path("evals/heldout_v1.protocol.yaml")
LOCK_FILE = Path("evals/heldout_v1.lock.yaml")
HELDOUT_STATUS = "running, results not yet archived"
CASE = "kalimantan-2015-burned-area"
MONTHS = ("2015-09", "2015-10")
PIPELINE = [
    ("Question and target variable", "implemented", "Registered cases fix area, period, variable"),
    ("Data QA and time availability", "implemented", "Valid-land fraction and reporting gate"),
    ("Train / validation / test split", "planned", "Chronological, gap-aware; no random split"),
    ("Deterministic baseline", "implemented", "Pre-registered MCD64A1 method; bench arm A"),
    ("Optional learned method", "planned", "Small regression or a compatible pretrained model"),
    ("Critique and independent score", "planned", "Typed plan critic is in a separate branch"),
]
BENCH_KEYS = (
    "runs",
    "passed",
    "completion",
    "false_verified",
    "errors",
    "median_seconds",
    "tool_calls",
    "provider_errors",
    "billed_inference_usd",
)


def _cards() -> None:
    cols = common.columns(4)
    with cols[0], common.panel("Default method", "implemented"):
        st.write("Deterministic, pre-registered method per case.")
    with cols[1], common.panel("Model training", "planned"):
        st.write("Not run. No model has been trained.")
    with cols[2], common.panel("Segmentation (Prithvi)", "planned"):
        st.write("Candidate only. Inputs and labels not checked.")
    with cols[3], common.panel("Experiment tracker (MLflow)", "planned"):
        st.write("Proposed for real experiments only. Not installed.")


def _pipeline() -> None:
    with common.panel("Investigation-to-experiment pipeline", "experimental"):
        rows = [
            {"step": f"{i}. {n}", "status": s, "note": t} for i, (n, s, t) in enumerate(PIPELINE, 1)
        ]
        st.table(rows)


@st.cache_data(show_spinner=False)
def qa_rows() -> list[dict[str, Any]]:
    """Valid-land fraction and gate result for each month and QA policy, from pinned data."""
    library = common.workspace().cases
    if library is None or CASE not in library.ids():
        return []
    case = library.get(CASE)
    rows = []
    for month in MONTHS:
        for policy in QaPolicy:
            report = month_report(case, library.root, month, policy)
            s = report["summary"]
            rows.append(
                {
                    "month (UTC)": month,
                    "QA policy": policy.value,
                    "valid-land fraction": round(float(s["valid_fraction"]), 3),
                    "gate": "pass" if s["gate_passed"] else "fail",
                    "area (ha)": s["primary_area_ha"] if s["gate_passed"] else None,
                    "verifier": "pass" if report["check"]["passed"] else "fail",
                }
            )
    return rows


def _method() -> None:
    with common.panel("Method selection record", "implemented", "From committed config."):
        method = yaml.safe_load(METHOD_FILE.read_text(encoding="utf-8"))
        gate = method.get("reporting_gate", {}).get("min_valid_fraction")
        st.table(
            [
                {"field": "Method", "value": f"{method['method_id']} v{method['version']}"},
                {"field": "Product", "value": method["product"]},
                {"field": "Reporting gate", "value": f"valid-land fraction >= {gate}"},
                {"field": "Learned model", "value": "not trained"},
            ]
        )
        st.dataframe(qa_rows(), use_container_width=True, hide_index=True)
        st.caption("Computed now from the pinned MCD64A1 files. Unit of area: hectares (ha).")


def _bench_table(bench: DevBench) -> list[dict[str, Any]]:
    return [
        {"arm": arm, **{k: values.get(k) for k in BENCH_KEYS}}
        for arm, values in sorted(bench.arms.items())
    ]


def _dev_bench() -> None:
    benches = find_dev_benches(common.RUNS_DIR)
    status: common.Status = "implemented" if benches else "unavailable"
    with common.panel(f"Development bench ({DEV_LABEL})", status):
        if not benches:
            st.write(
                "No development bench summary is in this deployment. No score is shown. "
                "Arm A is the deterministic dispatcher; arm B is the Muse investigator."
            )
            return
        bench = benches[0]
        st.dataframe(_bench_table(bench), use_container_width=True, hide_index=True)
        st.caption(
            f"{DEV_LABEL}. Code {bench.code_revision}; started {bench.started_at_utc}; "
            f"model {bench.model}; rows {bench.rows_written}/{bench.rows_expected}. "
            f"{bench.caveat}"
        )


def _heldout() -> None:
    with common.panel("Official held-out benchmark", "experimental", HELDOUT_STATUS):
        protocol = yaml.safe_load(PROTOCOL_FILE.read_text(encoding="utf-8"))
        lock = yaml.safe_load(LOCK_FILE.read_text(encoding="utf-8"))
        st.write(f"**Run status:** {HELDOUT_STATUS}.")
        st.write(
            f"Set {lock['set_id']}: {lock['questions']} sealed questions, arms "
            f"{', '.join(protocol['arms'])}, {protocol['repeats']} repeats, frozen "
            f"{protocol['frozen_at']}. Question text is never shown."
        )
        st.caption("No held-out score is shown until the owner archives the official result.")


def _experiments() -> None:
    with common.panel("Experiment comparison", "planned", "No experiment has run."):
        st.write("No chart is shown, because no model comparison exists yet.")
        st.button("Open MLflow tracking", disabled=True)
        st.caption(
            "Science metrics (for example area or PM2.5 error) and serving metrics (latency) "
            "will stay in separate views."
        )


def render() -> None:
    common.header(
        "Geospatial Engineering Lab",
        "Method selection, data quality and benchmark status for the engineer and reviewer.",
    )
    common.replay_notice()
    _cards()
    left, right = common.columns(2)
    with left:
        _pipeline()
        _dev_bench()
        _heldout()
    with right:
        _method()
        _experiments()
