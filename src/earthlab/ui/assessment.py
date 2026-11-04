"""Scientific council investigations (M4.1): replay of a recorded assessment run.

Reads `examples/assess/replay/<run>/result.json` and its hash-chained trace. It shows who took
part and on which checkpoint, the specialist findings with their code checks, the Lead's
answers, the critic and the Lead's response, the code rule and the human gate. No model runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from earthlab.trace import RunTrace, TraceIntegrityError

REPLAY = Path("examples/assess/replay")
ROLE_LABEL = {
    "data_specialist": "Data Specialist",
    "ml_engineer": "ML Specialist",
    "lead": "Engineering Lead",
    "critic": "Scientific Reviewer",
    "rebuttal": "Engineering Lead (response)",
    "pm": "Product Manager",
}


def runs(root: Path = REPLAY) -> list[str]:
    return sorted(p.name for p in root.glob("*") if (p / "result.json").exists())


def load(name: str, root: Path = REPLAY) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    folder = root / name
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    trace = RunTrace(folder / "trace.jsonl")
    try:
        integrity = f"hash chain verified, {trace.verify()} entries"
    except TraceIntegrityError as exc:
        integrity = f"hash chain broken: {exc}"
    return result, list(trace.records()), integrity


def roster(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "role": ROLE_LABEL.get(r["data"]["role"], r["data"]["role"]),
            "checkpoint": r["data"]["checkpoint_file"],
            "family": r["data"]["family"],
            "sha256": r["data"]["checkpoint_sha256"][:12],
        }
        for r in records
        if r["event"] == "role_binding"
    ]


def usage(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for r in records:
        if r["event"] != "model_turn":
            continue
        reply = r["data"].get("reply") or {}
        rows.append(
            {
                "role": ROLE_LABEL.get(r["data"]["role"], r["data"]["role"]),
                "attempt": r["data"]["attempt"],
                "provider": r["data"]["provider"],
                "completion tokens": reply.get("completion_tokens"),
                "seconds": reply.get("wall_seconds"),
                "contract fault": r["data"].get("fault") or "",
            }
        )
    return rows


def finding_rows(result: dict[str, Any], role: str) -> list[dict[str, Any]]:
    output = (result["roles"].get(role) or {}).get("output") or {}
    checks = {c["name"]: c for c in result["checks"].get(role, {}).get("checks", [])}
    rows = []
    for f in output.get("findings", []):
        check = checks.get(f"finding {f['id']}", {})
        rows.append(
            {
                "id": f["id"],
                "fault": f["fault_class"],
                "severity": f["severity"],
                "claim": f["claim"],
                "evidence": ", ".join(f["evidence"]),
                "code check": "backed"
                if check.get("passed")
                else f"not backed: {check.get('detail', '')}",
            }
        )
    return rows


def answers(result: dict[str, Any], role: str, key: str) -> list[dict[str, Any]]:
    output = (result["roles"].get(role) or {}).get("output") or {}
    return [
        {"finding": a["finding_id"], "answer": a["verdict"], "reason": a["reason"]}
        for a in output.get(key, [])
    ]


def _header(result: dict[str, Any], integrity: str) -> None:
    rule = result.get("code_rule", {})
    cols = st.columns(4)
    cols[0].metric("Decision proposed", result.get("decision", "none"))
    cols[1].metric("Code rule allows", ", ".join(rule.get("allowed", [])) or "none")
    cols[2].metric("Agrees with code rule", "yes" if result.get("agrees_with_code_rule") else "no")
    cols[3].metric(
        "Human decision", "pending" if result["status"] == "awaiting_human" else result["status"]
    )
    st.caption(
        f"Arm {result['arm']}. Package `{result['package_id']}`. {integrity}. "
        "Recorded replay. No model is called now."
    )


def _role_sections(result: dict[str, Any]) -> None:
    for role in ("data_specialist", "ml_engineer"):
        if role in result["roles"]:
            st.markdown(f"**{ROLE_LABEL[role]}** ({result['roles'][role]['provider']})")
            st.dataframe(finding_rows(result, role), hide_index=True, width="stretch")
    if "lead" in result["roles"]:
        st.markdown("**Engineering Lead: answers to the specialists**")
        st.dataframe(answers(result, "lead", "dispositions"), hide_index=True, width="stretch")
    if "critic" in result["roles"]:
        st.markdown(f"**Scientific Reviewer** ({result['roles']['critic']['provider']}, advisory)")
        st.dataframe(finding_rows(result, "critic"), hide_index=True, width="stretch")
    if "rebuttal" in result["roles"]:
        st.markdown("**Engineering Lead: response to the reviewer**")
        st.dataframe(answers(result, "rebuttal", "responses"), hide_index=True, width="stretch")


def render(root: Path = REPLAY) -> None:
    names = runs(root)
    if not names:
        st.info("No recorded council investigation is in this checkout.")
        return
    name = st.selectbox("Recorded investigation", names)
    result, records, integrity = load(name, root)
    _header(result, integrity)
    st.markdown("**Who took part** (checkpoint read from the trace)")
    st.dataframe(roster(records), hide_index=True, width="stretch")
    _role_sections(result)
    final = result.get("final", {})
    st.markdown("**Final plan sent to the human director**")
    st.write(final.get("plan", ""))
    st.write({"inputs used": final.get("inputs_used"), "excluded": final.get("excluded_inputs")})
    with st.expander("Code checks and model calls"):
        st.json(result["checks"], expanded=False)
        st.dataframe(usage(records), hide_index=True, width="stretch")
