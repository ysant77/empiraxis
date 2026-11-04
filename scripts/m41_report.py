"""Summarise M4.1 council runs and critic results into one evidence file.

Usage: python scripts/m41_report.py --runs DIR [DIR ...] --critic DIR [DIR ...] --out FILE

Critic results: only files scored under m41-v2 count ("scoring": "m41-v2").
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from earthlab.assess.contracts import EvidencePackageV1
from earthlab.assess.critic_bench import passes_gates
from earthlab.assess.score import load_keys, score_run
from earthlab.trace import RunTrace

PACKAGES = Path("examples/assess/packages")


def costs(trace: RunTrace) -> dict[str, Any]:
    per: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    load = 0.0
    for r in trace.records():
        d = r["data"]
        if r["event"] == "model_switch":
            load += d.get("load_seconds", 0.0)
        if r["event"] != "model_turn":
            continue
        reply = d.get("reply") or {}
        row = per[d["role"]]
        row["calls"] += 1
        row["repairs"] += d["attempt"] > 1
        row["tokens"] += (reply.get("prompt_tokens") or 0) + (reply.get("completion_tokens") or 0)
        row["seconds"] += reply.get("wall_seconds") or 0.0
    return {"per_role": {k: dict(v) for k, v in per.items()}, "load_seconds": round(load, 1)}


def council_rows(folders: list[Path]) -> list[dict[str, Any]]:
    keys = load_keys(Path("config/assess/answer-keys.yaml"))
    pkgs = {
        p.package_id: p
        for p in (
            EvidencePackageV1.model_validate_json(f.read_text()) for f in PACKAGES.glob("*.json")
        )
    }
    rows = []
    for folder in folders:
        result = json.loads((folder / "result.json").read_text())
        trace = RunTrace(folder / "trace.jsonl")
        pid = result["package_id"]
        row = {
            "run": folder.name,
            "arm": result["arm"],
            "package": pid,
            "temperature": result.get("temperature"),
            "wall_seconds": result["wall_seconds"],
            "trace_entries": trace.verify(),
            **costs(trace),
        }
        formed = next(r["data"] for r in trace.records() if r["event"] == "council_formed")
        row["critic_independent_checkpoint"] = formed.get("critic_independent_checkpoint")
        row["participation"] = result.get("participation")
        row["escalations"] = result.get("escalations", [])
        if result["status"] == "failed":
            row.update({"status": "failed", "reason": result.get("reason")})
        else:
            row.update(score_run(result, keys[pid], pkgs[pid]))
        rows.append(row)
    return rows


def critic_rows(folders: list[Path]) -> dict[str, Any]:
    found = {}
    for folder in folders:
        for p in folder.glob("critic-*.json"):
            body = json.loads(p.read_text())
            if body.get("scoring") == "m41-v2":
                found[body["critic"]] = body["summary"]
    rules = found.get("rules")
    gates = {k: passes_gates(v, rules) for k, v in found.items()} if rules else {}
    return {"scoring": "m41-v2", "summaries": found, "gates": gates}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, nargs="*", default=[])
    ap.add_argument("--critic", type=Path, nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    folders = sorted(f for root in a.runs for f in root.iterdir() if (f / "result.json").exists())
    body = {"protocol": "m41-v2", "critic": critic_rows(a.critic), "runs": council_rows(folders)}
    a.out.write_text(json.dumps(body, indent=1) + "\n")
    print(len(body["critic"]["summaries"]), "critics,", len(body["runs"]), "runs")


if __name__ == "__main__":
    main()
