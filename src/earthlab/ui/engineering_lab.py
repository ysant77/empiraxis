"""Geospatial Engineering Lab: method choice, data QA and benchmark status, read-only.

Every number here comes from pinned data, committed config, a recorded development bench
summary or the independent evaluator of an experiment run. Only experiment E1 has trained a
model, on validation only; its numbers appear only on an E1 run.
The official held-out panel states its run status only, until the owner supplies results.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st
import yaml

from earthlab.events.bench import DEV_LABEL, DevBench, find_dev_benches
from earthlab.science.burned_area import QaPolicy
from earthlab.tools.burned_area_tools import month_report
from earthlab.ui import board_view, common, experiments, lab_data, story_view
from earthlab.ui.story_view import Opened, section

METHOD_FILE = Path("config/methods/mcd64a1_burned_area.yaml")
PROTOCOL_FILE = Path("evals/heldout_v1.protocol.yaml")
LOCK_FILE = Path("evals/heldout_v1.lock.yaml")
RESULTS_FILE = Path("evals/results/heldout-v1/summary.json")
HELDOUT_STATUS = "archived; measured at an older code revision"
HELDOUT_KEYS = ("runs", "passed", "false_verified", "errors", "median_seconds")
CASE = "kalimantan-2015-burned-area"
MONTHS = ("2015-09", "2015-10")
PIPELINE = [
    ("Question and target variable", "implemented", "Registered cases fix area, period, variable"),
    ("Data QA and time availability", "implemented", "Valid-land fraction and reporting gate"),
    ("Train / validation / test split", "experimental", "E1: chronological, per protocol"),
    ("Deterministic baseline", "implemented", "Pre-registered MCD64A1 method; bench arm A"),
    ("Optional learned method", "experimental", "E1: one small neural model, validation only"),
    ("Plan critique", "implemented", "Deterministic plan critic, code, not a model"),
    ("Independent score", "implemented", "Deterministic verifier recomputes every claim"),
    ("Implementation workers", "planned", "Typed contracts only; no worker runs code"),
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
                {"field": "Learned model", "value": "none for burned area"},
            ]
        )
        st.dataframe(qa_rows(), width="stretch", hide_index=True)
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
        st.dataframe(_bench_table(bench), width="stretch", hide_index=True)
        st.caption(
            f"{DEV_LABEL}. Code {bench.code_revision}; started {bench.started_at_utc}; "
            f"model {bench.model}; rows {bench.rows_written}/{bench.rows_expected}. "
            f"{bench.caveat}"
        )


def _heldout() -> None:
    with common.panel("Official held-out benchmark", "implemented", HELDOUT_STATUS):
        protocol = yaml.safe_load(PROTOCOL_FILE.read_text(encoding="utf-8"))
        lock = yaml.safe_load(LOCK_FILE.read_text(encoding="utf-8"))
        st.write(
            f"Set {lock['set_id']}: {lock['questions']} sealed questions, arms "
            f"{', '.join(protocol['arms'])}, {protocol['repeats']} repeats, frozen "
            f"{protocol['frozen_at']}. Question text is never shown."
        )
        if not RESULTS_FILE.is_file():
            st.caption(common.status_text("unavailable", "The archived summary is missing."))
            return
        summary = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        # Arm totals only: per-question rows would name sealed question IDs.
        st.table(
            [
                {"arm": arm, **{k: totals.get(k) for k in HELDOUT_KEYS}}
                for arm, totals in summary["arms"].items()
            ]
        )
        revision = str(summary["meta"]["code_revision"])[:7]
        st.caption(
            f"Measured once at code revision {revision}. Later changes do not inherit these "
            "counts, and the set is spent: it is not re-run to claim an improvement. "
            f"{summary.get('caveat', '')}"
        )


def evidence_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per plan review and month check of a run, from its saved record."""
    rows: list[dict[str, Any]] = [
        {"check": f"plan critic r{r['plan_revision']}", "result": r["verdict"], "source": "code"}
        for r in result.get("plan_reviews") or []
    ]
    for rnd in result.get("area_rounds") or []:
        rows += [
            {
                "check": f"area claim {v['claim']['month']}",
                "result": v["verdict"],
                "source": "verifier",
            }
            for v in rnd
        ]
    return rows


def _run_evidence() -> None:
    picked = common.pick_run()
    if picked is not None:
        board_view.run_panel(*picked)
    with common.panel("Recorded run evidence", "implemented", "The run chosen on any surface."):
        run_dir = None if picked is None else common.open_run(*picked)[0]
        if picked is not None and board_view.is_waiting(picked[0]) and run_dir is None:
            st.write("This run has no trace yet.")
            return
        if run_dir is None:
            st.write("No recorded run passed its integrity check.")
            return
        path = run_dir / "result.json"
        if not path.is_file():
            st.write("This run has no result yet. Evidence appears when it ends.")
            return
        result = json.loads(path.read_text(encoding="utf-8"))
        st.write(
            f"Status: {result['status']}. {len(evidence_files(result))} input hashes recorded."
        )
        st.dataframe(evidence_rows(result), width="stretch", hide_index=True)
    experiments.experiment_panel(run_dir)
    with common.panel("Specialist tasks", "experimental", "From this run's own record."):
        _specialist(run_dir, result)


def evidence_files(result: dict[str, Any]) -> dict[str, str]:
    files: dict[str, str] = (result.get("evidence") or {}).get("files", {})
    return files


def specialist_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """The specialist's table from a delegation record, with its acceptance result."""
    block = result.get("result") or {}
    return [dict(row) for row in block.get("rows") or []]


def _specialist(run_dir: Path, result: dict[str, Any]) -> None:
    """Executed specialist work only: a run without a ticket shows no specialist row."""
    ticket = result.get("ticket")
    if "evidence_label" in result:
        st.caption("This experiment's specialist tasks are in its experiment panel.")
        return
    if ticket is None:
        st.caption("This run has no specialist ticket.")
        return
    block = result.get("result") or {}
    acceptance = block.get("acceptance") or {}
    author = block.get("author") or {}
    st.write(
        f"Ticket {ticket['task_id']}, owner {ticket['owner']}, served by "
        f"{author.get('provider')} / {author.get('model')}. Result: {result['status']}. "
        f"Parent run {result.get('parent_run_id')}."
    )
    st.dataframe(specialist_rows(result), width="stretch", hide_index=True)
    st.dataframe(acceptance.get("checks", []), width="stretch", hide_index=True)
    st.caption(f"Artifact {ticket['artifact']}, sha256 {str(block.get('rows_sha256'))[:16]}...")
    st.caption(f"Saved in {run_dir.name}. Code recomputed every row; no model decided a check.")


def _artifacts(opened: Opened) -> None:
    files = opened.entry.get("files", {})
    story_view.table([{"File": name, "sha256": sha[:16]} for name, sha in sorted(files.items())])


def _verification(opened: Opened) -> None:
    ready = lab_data.readiness(opened.story.key, opened.run_dir)
    if ready is None:
        st.write("This scenario has no model bundle to verify.")
    else:
        checks = ready["integrity_checks"]
        passed = sum(c["passed"] for c in checks)
        st.write(
            f"Bundle {ready['model_name']}: {ready['verification_outcome']}, {passed} of "
            f"{len(checks)} checks passed. {lab_data.inference_line(ready)}"
        )
        story_view.table(
            [
                {
                    "Check": c["name"],
                    "Passed": "yes" if c["passed"] else "no",
                    "Detail": c["detail"],
                }
                for c in checks
            ]
        )
    with st.expander("Artifact digests"):
        _artifacts(opened)


def _story(opened: Opened) -> None:
    story, run_dir = opened.story, opened.run_dir
    st.subheader(story.title)
    section("Datasets and availability")
    rows = lab_data.data_rows(story.key, run_dir)
    if rows:
        story_view.table(rows)
    section("Alternatives and execution")
    st.write(lab_data.execution(story.key, run_dir))
    rows = lab_data.alternatives(run_dir)
    if rows:
        story_view.table(rows)
    else:
        st.caption("This packaged result holds no suitability record.")
    section(story.rows_title)
    story_view.table(story.rows)
    extra = lab_data.extra_comparison(story.key, run_dir)
    if extra:
        st.caption("Other model families, with recall in elevated hours. Same evaluator.")
        story_view.table(extra)
    limits = lab_data.negatives(story.key, run_dir)
    if limits:
        section("Negative results and subgroup limits")
        st.markdown("\n".join(f"- {line}" for line in limits))
    section("Features, models and inference")
    _verification(opened)
    story_view.identity(opened)


def _advanced() -> None:
    with st.expander("Advanced: pipeline, benchmarks and recorded run evidence"):
        _pipeline()
        _dev_bench()
        _heldout()
        _run_evidence()
        _method()


def render(label: str | None) -> None:
    st.caption("Data, alternatives, comparisons and verification, for the engineer and reviewer.")
    opened = story_view.open_story(label) if label else None
    if opened is not None:
        _story(opened)
    _advanced()
