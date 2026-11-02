"""Who did each step of a saved run, from its trace.

A step is credited to a model only when the trace records that model's checked proposal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from earthlab.trace import RunTrace

TEXT_KEYS = ("note", "reason", "action", "strategy", "outcome")
SAID_LIMIT = 200


def said(proposal: dict[str, Any]) -> str:
    parts = [str(proposal[k]) for k in TEXT_KEYS if proposal.get(k)]
    text = " | ".join(parts)
    return text if len(text) <= SAID_LIMIT else text[: SAID_LIMIT - 1] + "…"


def steps(run: Path) -> list[tuple[str, str, str]]:
    roles = json.loads((run / "result.json").read_text("utf-8")).get("roles") or {}
    out = []
    for entry in RunTrace(run / "trace.jsonl").records():
        event, data = entry["event"], entry["data"]
        if event == "proposal_reviewed" and data["valid"]:
            who = roles.get(data["role"], {}).get("served_model", "unknown model")
            out.append((f"{who} ({data['role']})", data["tool"], said(data["proposal"])))
        elif event == "tool_result":
            out.append(("deterministic code", data["name"], data["outcome"]))
        elif event == "harness_transition" and entry["actor"] == "evaluator":
            out.append(("independent evaluator code", "score", "wrote the evaluation report"))
    out.append(("human", "decision", "pending: no human decision is recorded"))
    return out
