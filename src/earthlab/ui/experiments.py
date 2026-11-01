"""Experiment E1 on the Lab and the Control Room, from the run's own record.

Every number comes from the independent evaluator. Model free text is not shown. This is a
historical evaluation, so each view prints the required label and limits.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import streamlit as st

from earthlab.board.progress import fold
from earthlab.digest import file_digest
from earthlab.harness.lifecycle import Lifecycle
from earthlab.team.resources import ResourceApprovalV1, key_matches, operator_key, sign
from earthlab.ui import board_view, common

DECISION_FILE = "decision.json"
APPROVER = "local operator (holder of the operator key)"
UNLOCKED = "Scored on validation only. The test period is not evaluated."


def record_of(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "result.json"
    if not path.is_file():
        return None
    record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return record if "evidence_label" in record and "arm" in record else None


def _usage_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"measure": k, "value": str(v)} for k, v in (record.get("usage") or {}).items()]


def _roles(record: dict[str, Any]) -> list[dict[str, Any]]:
    return list((record.get("roles") or {}).values())


def _tasks(run_dir: Path) -> list[dict[str, Any]]:
    """The experiment's task tree, from its trace, as every other surface shows it."""
    entries = board_view.read_trace(run_dir)
    return board_view.task_rows(fold(run_dir.name, entries).tasks)


def experiment_panel(run_dir: Path) -> None:
    record = record_of(run_dir)
    if record is None:
        return
    with common.panel("Experiment E1", "experimental", record["evidence_label"]):
        st.warning(" ".join(record["limitations"]))
        rec = record.get("recommendation") or {}
        st.write(
            f"Arm {record['arm']}. Status {record['status']}. Recommendation: "
            f"{rec.get('outcome', 'none')} {rec.get('model_id') or ''}. {UNLOCKED}"
        )
        st.dataframe(record.get("comparison", []), use_container_width=True, hide_index=True)
        st.caption(
            "Skill is against persistence at +6 h, with 95% block-bootstrap limits. "
            "Evaluator: separate code that reads the published file and stored predictions."
        )
        if record.get("tiers"):
            st.dataframe(record["tiers"], use_container_width=True, hide_index=True)
            pair = record.get("distillation") or {}
            st.write(
                f"Distillation helped against the direct student: {pair.get('helped')}. "
                "This is a rehearsal on PM2.5 data, not a Prithvi result."
            )
        checks = record.get("acceptance") or {}
        st.table([{"check": k, "passed": v} for k, v in checks.items()])
        st.dataframe(_tasks(run_dir), use_container_width=True, hide_index=True)
        st.dataframe(_roles(record), use_container_width=True, hide_index=True)
        st.dataframe(_usage_rows(record), use_container_width=True, hide_index=True)


def request_panel() -> None:
    """The request, its scope and the verified recommendation of the run named in the URL."""
    label = st.query_params.get("run", "")
    run_dir = dict(common.run_choices()).get(label)
    record = record_of(run_dir) if run_dir is not None else None
    if run_dir is None or record is None:
        return
    with common.panel("Experiment request", "experimental", "Recorded run, not a live answer."):
        path = run_dir / "artifacts" / "request.json"
        if path.is_file():
            st.write(json.loads(path.read_text(encoding="utf-8"))["objective"])
        rec = record.get("recommendation") or {}
        st.write(
            f"Run {label}. Arm {record['arm']}. Strategy {record.get('strategy')}. Status "
            f"{record['status']}. Recommendation: {rec.get('outcome', 'none')} "
            f"{rec.get('model_id') or ''}. A person decides. {UNLOCKED}"
        )
        st.warning(" ".join(record["limitations"]))


def decide(run_dir: Path, approve: bool, key: str) -> ResourceApprovalV1:
    """Sign one decision on this exact record. The first decision stands."""
    if not key_matches(key):
        raise PermissionError("the operator key is not valid")
    approval = ResourceApprovalV1(
        request_id=run_dir.name, request_sha256=file_digest(run_dir / "result.json"),
        approved=approve, approver=APPROVER, decided_at_utc=datetime.now(UTC),
    )  # fmt: skip
    signed = approval.model_copy(update={"signature": sign(approval, key)})
    with (run_dir / DECISION_FILE).open("x", encoding="utf-8") as out:
        out.write(signed.model_dump_json(indent=2))
    if (run_dir / "artifacts").is_dir():
        Lifecycle(run_dir).human_decision(signed, approval.request_sha256, key)
    return signed


def decision_panel(run_dir: Path | None) -> None:
    """The Human Director's step, for a local operator only."""
    if common.ui_mode() != "operator" or run_dir is None:
        return
    record = record_of(run_dir)
    if record is None or record["status"] != "awaiting_human":
        return
    with common.panel("Experiment recommendation", "experimental", "A person decides."):
        rec = record["recommendation"]
        st.write(f"Recommendation: {rec['outcome']} {rec.get('model_id') or ''}. {UNLOCKED}")
        path = run_dir / DECISION_FILE
        if path.is_file():
            saved = ResourceApprovalV1.model_validate_json(path.read_text(encoding="utf-8"))
            st.write(f"Decided: accepted {saved.approved}, at {saved.decided_at_utc} UTC.")
            return
        if operator_key() is None:
            st.warning("No operator key is set, so this cannot be decided here.")
            return
        key = st.text_input("Operator key", type="password", key=f"key-{run_dir.name}")
        accept, reject = common.columns(2)
        for column, label, value in ((accept, "Accept", True), (reject, "Reject", False)):
            if column.button(label, key=f"{label}-{run_dir.name}", disabled=not key):
                try:
                    decide(run_dir, value, key)
                    st.success("The decision is signed and recorded.")
                except (PermissionError, FileExistsError) as exc:
                    st.error(f"Refused: {exc}")
