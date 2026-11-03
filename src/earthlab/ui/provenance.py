"""What really happened in a scenario: roles, stages and the six kinds of evidence.

Built from the verified trace and the run's own record. A role appears only if the trace
shows that it took part.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from earthlab.ui.scenarios import read, record_of

CODE_ACTORS = {
    "runtime": ("Harness runtime", "Stored artifacts and started each step"),
    "controller": ("Trusted controller", "Checked every state change"),
    "evaluator": ("Independent evaluator", "Wrote the evaluation report"),
}
MODEL_SEATS = {
    "product_manager": "PM",
    "geospatial_engineer": "Lead",
    "data_specialist": "Data specialist",
    "ml_engineer": "ML engineer",
    "scientific_critic": "Reviewer",
    "method_critic": "Critic",
}
SAME_MODEL_CRITIC = (
    "The method critic is a same-model second pass: Muse Glimmer reads Muse Glimmer's plan. "
    "It is not an independently served reviewer."
)
INDEPENDENT_CRITIC = (
    "The critic ran on a different checkpoint from the Lead. Its findings are advisory. "
    "Code checks every number it cites. It sets no score, outcome or approval."
)
NO_CRITIC = (
    "No critic took part in this run. The method-review gate is off by default. "
    + SAME_MODEL_CRITIC
)


@dataclass(frozen=True)
class HumanGate:
    open: bool
    state: str
    detail: str


def _trace(run_dir: Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Own-execution or packaging trace, decided by what the trace itself recorded."""
    start = next((e for e in entries if e["event"] == "experiment_start"), None)
    note = (start or {}).get("data", {}).get("note", "")
    return {"packaging": "packaging" in note, "note": note}


def is_packaging(entries: list[dict[str, Any]]) -> bool:
    return bool(_trace(Path(), entries)["packaging"])


def human_gate(run_dir: Path, entry: dict[str, Any]) -> HumanGate:
    """The gate state comes from the run's decision file and its signed approvals."""
    record = record_of(run_dir)
    if record["status"] != "awaiting_human":
        return HumanGate(
            False, "No human decision is open",
            str(entry.get("planned", "")).removeprefix("None. "),
        )  # fmt: skip
    saved = (
        read(run_dir, "decision.json").get("human_status", "pending")
        if (run_dir / "decision.json").is_file()
        else "pending"
    )
    if saved != "pending":
        return HumanGate(False, f"Human decision: {saved}", "Recorded in the run.")
    return HumanGate(True, "Human decision pending", "No signed approval is recorded in this run.")


def bindings(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The recorded checkpoint of each seat, by role. Empty for a run without bindings."""
    return {e["data"]["role"]: e["data"] for e in entries if e["event"] == "role_binding"}


def _seat_row(role: str, seat: dict[str, Any], bound: dict[str, Any] | None) -> dict[str, Any]:
    row = {
        "Role": MODEL_SEATS.get(role, role),
        "Kind": f"model: {seat.get('served_model', 'unknown')}",
        "Work": f"{seat.get('calls', 0)} model calls",
        "Trace records": seat.get("calls", 0),
    }
    if bound is not None:
        row |= {
            "Family": bound["family"],
            "Checkpoint": bound["checkpoint_file"],
            "SHA-256": str(bound["checkpoint_sha256"])[:12],
        }
    return row


def participants(entries: list[dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    """Only actors the trace holds, plus model seats with recorded calls."""
    counts: dict[str, int] = {}
    for item in entries:
        counts[item["actor"]] = counts.get(item["actor"], 0) + 1
    rows = [
        {"Role": name, "Kind": "code", "Work": work, "Trace records": counts[actor]}
        for actor, (name, work) in CODE_ACTORS.items()
        if actor in counts
    ]
    bound = bindings(entries)
    rows += [_seat_row(r, seat, bound.get(r)) for r, seat in (record.get("roles") or {}).items()]
    if bound:  # every row needs every column, so the table stays rectangular
        rows = [{"Family": "", "Checkpoint": "", "SHA-256": ""} | row for row in rows]
    return rows


def stages(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "From": e["data"].get("from", ""),
            "To": e["data"].get("to", ""),
            "By": e["actor"],
            "Detail": e["data"].get("outcome") or e["data"].get("plan") or "",
        }
        for e in entries
        if e["event"] == "harness_transition"
    ]


def critic_note(record: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    critique = next((e["data"] for e in entries if e["event"] == "decision_critique"), None)
    if critique is not None and critique.get("critic_source") == "independent_model":
        return INDEPENDENT_CRITIC
    ran = any("critique" in str(e["event"]) for e in entries) or record.get("review")
    return SAME_MODEL_CRITIC if ran else NO_CRITIC


def evidence_ladder(
    run_dir: Path, entry: dict[str, Any], entries: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """The six kinds of evidence, each stated for this scenario."""
    record = record_of(run_dir)
    packaging = is_packaging(entries)
    usage = record.get("usage") or {}
    calls = usage.get("model_calls")
    gate = human_gate(run_dir, entry)
    models = _model_sentence(record, bindings(entries), calls)
    return [
        {"Kind": "Original real execution", "In this scenario": str(entry["evidence_mode"])},
        {
            "Kind": "Recorded replay",
            "In this scenario": "Yes. This page reads saved files. No model or training runs now.",
        },
        {
            "Kind": "Result packaging",
            "In this scenario": "Yes. This trace records packaging, not the original job."
            if packaging
            else "No packaging trace. This is the run's own trace.",
        },
        {
            "Kind": "Deterministic evaluation",
            "In this scenario": "Yes. Code computed every score and the rule outcome.",
        },
        {
            "Kind": "Model-assisted decisions",
            "In this scenario": models if calls else "None. No Muse call is recorded in this run.",
        },
        {"Kind": "Human action", "In this scenario": f"{gate.state}. {gate.detail}"},
    ]


def _model_sentence(record: dict[str, Any], bound: dict[str, dict[str, Any]], calls: Any) -> str:
    """Who made the model calls. A run with recorded bindings names every checkpoint."""
    if not bound:
        return f"Yes. {calls} Muse Glimmer calls. Code checked each proposal."
    per: dict[str, int] = {}
    for role, seat in (record.get("roles") or {}).items():
        name = bound[role]["logical_model"] if role in bound else "unrecorded"
        per[name] = per.get(name, 0) + int(seat.get("calls", 0))
    parts = ", ".join(f"{n}: {c}" for n, c in sorted(per.items()))
    return f"Yes. {calls} model calls on {len(per)} model(s) ({parts}). Code checked each proposal."
