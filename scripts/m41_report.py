"""Summarise M4.1 council runs and critic results into one evidence file.

Usage: python scripts/m41_report.py --runs DIR [DIR ...] --critic DIR --out FILE
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from earthlab.assess.contracts import EvidencePackageV1
from earthlab.assess.critic_bench import choose_critic, passes_gates
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
        if result["status"] == "failed":
            row.update({"status": "failed", "reason": result.get("reason")})
        else:
            row.update(score_run(result, keys[pid], pkgs[pid]))
        rows.append(row)
    return rows


def critic_rows(folder: Path) -> dict[str, Any]:
    found = {
        json.loads(p.read_text())["critic"]: json.loads(p.read_text())["summary"]
        for p in folder.glob("critic-*.json")
    }
    rules = found.get("rules")
    gates = {k: passes_gates(v, rules) for k, v in found.items()} if rules else {}
    chosen, passed = choose_critic(found, "local-glimmer") if rules else (None, False)
    return {"summaries": found, "gates": gates, "chosen": chosen, "chosen_passed": passed}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, nargs="*", default=[])
    ap.add_argument("--critic", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    folders = sorted(f for root in a.runs for f in root.iterdir() if (f / "result.json").exists())
    body = {"protocol": "m41-v1", "critic": critic_rows(a.critic), "runs": council_rows(folders)}
    a.out.write_text(json.dumps(body, indent=1) + "\n")
    print(json.dumps(body["critic"]["chosen"]), len(body["runs"]), "runs")


if __name__ == "__main__":
    main()
