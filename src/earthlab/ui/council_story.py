"""M4: a recorded run where different model checkpoints took different seats.

Built only from the redacted replay copy. Every checkpoint named on the page comes from a
`role_binding` record in the run's own trace, so the page never names a model the run did not use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from earthlab.ui import method_story
from earthlab.ui import scenarios as S
from earthlab.ui.provenance import bindings

MODEL_NAMES = {
    "muse-glimmer-30b": "Muse Glimmer 30B",
    "llama-3.2-3b-instruct": "Llama 3.2 3B Instruct",
    "qwen3-4b-instruct-2507": "Qwen3 4B Instruct 2507",
}
SEATS = {
    "product_manager": "PM", "geospatial_engineer": "Lead", "data_specialist": "Data specialist",
    "ml_engineer": "ML specialist", "method_critic": "Critic",
}  # fmt: skip


def _name(bound: dict[str, Any]) -> str:
    return MODEL_NAMES.get(str(bound["logical_model"]), str(bound["logical_model"]))


def _seat_lines(bound: dict[str, dict[str, Any]], roles: dict[str, Any]) -> list[str]:
    return [
        f"{SEATS.get(r, r)}: {_name(b)} ({b['family']}), file {b['checkpoint_file']}, SHA-256 "
        f"{str(b['checkpoint_sha256'])[:12]}, {roles.get(r, {}).get('calls', 0)} model calls."
        for r, b in bound.items()
    ]  # fmt: skip


def _critic_lines(critique: dict[str, Any] | None) -> list[str]:
    if critique is None:
        return ["No decision critic ran in this run."]
    found = critique.get("findings") or []
    lines = [
        f"Critic ({critique['critic_source']}): state {critique['state']}, verdict "
        f"{critique['verdict']}, {sum(bool(f['backed']) for f in found)} of {len(found)} "
        "finding(s) match the evaluator's numbers. It is advisory and sets no score or outcome."
    ]
    return lines + [f"Finding ({f['kind']}): {f['claim']}" for f in found]


def m4(run_dir: Path) -> S.Story:
    record = S.record_of(run_dir)
    entries = method_story.entries(run_dir)
    bound = bindings(entries)
    if not bound:
        raise ValueError("this run has no role_binding records")
    council, usage = record["council"], record["usage"]
    critique = record.get("decision_critique")
    names = sorted({_name(b) for b in bound.values()})
    pick = record["recommendation"]
    tile_critic = "none" if critique is None else str(critique["state"])
    return S.Story(
        key="M4", run=run_dir.name, title=S.TITLES["M4"],
        question=method_story.QUESTION,
        method="The seats were served by different checkpoints: " + "; ".join(
            _seat_lines(bound, record["roles"])
        ) + " Trusted tools trained and reloaded the models. Separate code scored every model.",
        evidence=[
            f"{usage['model_calls']} model calls on {council['distinct_checkpoints']} "
            f"checkpoint(s) ({', '.join(names)}) in a hash-chained trace.",
            *_critic_lines(critique),
            "Code checked every proposal. The verifier, scores and approvals are not model output.",
            "Validation years 2019 to 2023 were used in earlier experiments, so this is not an "
            "independent score.",
        ],
        tiles=[
            S.Tile("Model calls", str(usage["model_calls"]), ", ".join(names)),
            S.Tile("Checkpoints", str(council["distinct_checkpoints"]),
                   "heterogeneous" if council["heterogeneous"] else "one checkpoint"),
            S.Tile("Critic", tile_critic, "advisory"),
            S.Tile("Wall time (s)", f"{usage['wall_seconds']:,.1f}"),
        ],
        rows=method_story.rows(record, method_story.neural_name(entries)),
        rows_title="Model comparison, same validation rows",
        decision=S.outcome_name(pick["outcome"]) + ": " + S.model_name(str(pick["model_id"])),
        why=pick["reason"],
        limits=[line.replace("ug/m3", S.UNIT) for line in record["limitations"]],
    )  # fmt: skip
