"""Read M4 matrix output folders and print the matched table. It reads files; it runs nothing.

A folder holds `manifest.jsonl` (one row per attempt) and `runs/<id>/result.json`. Every attempt
is a row, so a failed attempt before a completed one stays visible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

COLUMNS = (
    "arm", "attempt", "status", "recommendation", "code_outcome", "calls", "tokens", "wall_s",
    "checkpoints", "critic",
)  # fmt: skip


def _critic(result: dict[str, Any]) -> str:
    c = result.get("decision_critique")
    if not c:
        return "none"
    found = c.get("findings") or []
    backed = sum(bool(f.get("backed")) for f in found)
    source = "indep" if c.get("critic_source") == "independent_model" else "same"
    return f"{c['state']}/{source}/{backed} backed"


def _row(manifest_row: dict[str, Any], result: dict[str, Any] | None, label: str) -> dict[str, Any]:
    base = {
        "arm": manifest_row["arm_id"], "attempt": label, "status": manifest_row["status"],
        "wall_s": manifest_row["wall"], "scenario": manifest_row["scenario"],
        "error": manifest_row.get("err", ""),
    }  # fmt: skip
    if result is None:
        return base | {k: "-" for k in COLUMNS if k not in base}
    usage, rec = result.get("usage") or {}, result.get("recommendation") or {}
    council = result.get("council") or {}
    return base | {
        "recommendation": f"{rec.get('outcome')}:{rec.get('model_id')}" if rec else "-",
        "code_outcome": result.get("code_outcome", "-"),
        "calls": usage.get("model_calls", 0),
        "tokens": (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0),
        "checkpoints": council.get("distinct_checkpoints", "-"),
        "critic": _critic(result),
    }


def collect(folders: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for folder in folders:
        manifest = folder / "manifest.jsonl"
        if not manifest.is_file():
            continue
        for line in manifest.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if "arm_id" not in row:
                continue
            path = Path(row["run"]) / "result.json"
            result = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
            rows.append(_row(row, result, folder.name))
    return rows


def table(rows: list[dict[str, Any]]) -> str:
    out = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    out += ["| " + " | ".join(str(r[c]) for c in COLUMNS) + " |" for r in rows]
    return "\n".join(out)
