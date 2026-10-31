"""Live console lines for a run: one short line per trace entry the operator cares about."""

from __future__ import annotations

import sys
from typing import Any


def print_event(record: dict[str, Any]) -> None:
    data = record["data"]
    event = record["event"]
    if event == "model_turn":
        calls = ", ".join(c["name"] for c in data["tool_calls"]) or "text answer"
        print(f"[turn {data['turn']}] model -> {calls} ({data['wall_seconds']:.1f} s)")
    elif event == "tool_result":
        line = f"    {data['name']}: {data['outcome']}"
        if data["name"] == "submit_findings" and data.get("data"):
            verdicts = [
                f"{v['kind']}/{v['region']}={v['verdict']}" for v in data["data"]["verdicts"]
            ]
            line += " | " + "; ".join(verdicts)
        elif data.get("error"):
            line += f" | {data['error'][:120]}"
        print(line)
    elif event == "safety_check":
        verdict = "allowed" if data["allowed"] else f"BLOCKED by {data['blocked_by']}"
        print(f"[safety {data['stage']}] {verdict} | {data.get('guard') or 'rules only'}")
    elif event == "finish":
        print(f"[finish] status={data['status']} ({data['reason']})")
    sys.stdout.flush()
