"""Markdown tables for the M4.1 report, from the evidence file that m41_report.py writes.

Every number in the tables comes from that file. Nothing is typed by hand.

Usage: python scripts/m41_tables.py EVIDENCE.json > tables.md
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from earthlab.assess.score import load_keys

ARMS = ["F", "S", "T", "H", "HC"]
MAIN = "local-glimmer"
SPECIALISTS = ("data_specialist", "ml_engineer", "critic")


def table(head: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def rule_raised(run: dict[str, Any], keys: dict[str, Any]) -> int:
    """Known faults that the code rule's own flags match (fault class and a key evidence id)."""
    key = keys[run["package"]]
    flags = run.get("code_rule_flags", [])
    return sum(
        any(
            f["fault_class"] == k.fault_class and set(f["evidence"]) & set(k.evidence)
            for f in flags
        )
        for k in key.known_faults
    )


def calls(run: dict[str, Any], muse: bool) -> tuple[int, float, float]:
    n = tok = sec = 0.0
    for role, row in run.get("per_role", {}).items():
        is_muse = (
            run["participation"]["executed"].get(role) == MAIN
            if run.get("participation")
            else False
        )
        if is_muse == muse:
            n, tok, sec = n + row["calls"], tok + row["tokens"], sec + row["seconds"]
    return int(n), tok, sec


def decisions(runs: list[dict[str, Any]]) -> str:
    by = {(r["package"], r["arm"]): r for r in runs if r.get("temperature") in (0.0, None)}
    packages = sorted({r["package"] for r in runs})
    rows = []
    for p in packages:
        row: list[Any] = [p]
        for a in ARMS:
            r = by.get((p, a))
            if r is None:
                row.append("not run")
            elif r.get("status") == "failed":
                row.append(f"FAILED ({r.get('reason')})")
            else:
                mark = "correct" if r["decision_correct"] else "WRONG"
                row.append(f"{r['decision']} ({mark})")
        rows.append(row)
    return table(["package", *ARMS], rows)


def arm_totals(runs: list[dict[str, Any]], keys: dict[str, Any]) -> str:
    rows = []
    for a in ARMS:
        rs = [r for r in runs if r["arm"] == a and r.get("temperature") in (0.0, None)]
        if not rs:
            continue
        ok = [r for r in rs if r.get("status") != "failed"]
        muse = [calls(r, True) for r in rs]
        small = [calls(r, False) for r in rs]
        rows.append(
            [
                a,
                len(rs),
                len(rs) - len(ok),
                sum(r["decision_correct"] for r in ok),
                sum(bool(r["agrees_with_code_rule"]) for r in ok),
                f"{sum(len(r['known_faults_raised']) for r in ok)}/"
                f"{sum(r['known_faults'] for r in rs)}",
                sum(rule_raised(r, keys) for r in rs),
                sum(c["unsupported_finding"] for r in ok for c in r["contribution"].values()),
                sum(len(r["failed_plan_checks"]) for r in ok),
                sum(len(r["unexcluded_inputs"]) for r in ok),
                sum(len(r.get("escalations", [])) for r in rs),
                sum(m[0] for m in muse),
                sum(s[0] for s in small),
                int(sum(m[1] + s[1] for m, s in zip(muse, small, strict=True))),
                round(sum(r["wall_seconds"] for r in rs) / 60, 1),
                round(sum(r["load_seconds"] for r in rs), 1),
            ]
        )
    head = [
        "arm", "runs", "failed", "correct", "agrees with rule", "known faults raised by models",
        "known faults in rule flags", "unsupported findings", "failed plan checks",
        "unexcluded inputs", "escalations", "Muse calls", "small-model calls", "tokens",
        "wall minutes", "load seconds",
    ]  # fmt: skip
    return table(head, rows)


def contributions(runs: list[dict[str, Any]]) -> str:
    agg: dict[tuple[str, str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in runs:
        if r.get("temperature") not in (0.0, None) or r.get("status") == "failed":
            continue
        for role, c in r["contribution"].items():
            prov = r["participation"]["executed"].get(role, "?")
            row = agg[(r["arm"], role, prov)]
            row["runs"] += 1
            row["valid"] += c["valid_output"]
            row["findings"] += c["findings"]
            row["detected known fault"] += c["detected_known_fault"]
            row["new backed concern"] += c["new_backed_concern"]
            row["unsupported"] += c["unsupported_finding"]
            row["redundant with rule"] += c["redundant"]
            row["accepted by Lead"] += c["accepted_by_lead"]
    cols = ["runs", "valid", "findings", "detected known fault", "new backed concern",
            "unsupported", "redundant with rule", "accepted by Lead"]  # fmt: skip
    rows = [[a, role, p, *(v[c] for c in cols)] for (a, role, p), v in sorted(agg.items())]
    return table(["arm", "role", "checkpoint", *cols], rows)


def critics(critic: dict[str, Any]) -> str:
    rows = []
    for name, s in sorted(critic["summaries"].items()):
        g = critic["gates"].get(name, {})
        rows.append(
            [
                name,
                f"{s['usable']}/{s['cases']}",
                f"{s.get('faults_detected_raw', '-')}/{s['faults']}",
                f"{s['faults_detected']}/{s['faults']}",
                f"{s['clean_with_high_finding']}/{s['clean']}",
                s["findings"],
                s["unsupported_findings"],
                "pass"
                if g and all(g.values())
                else "fail: " + ", ".join(k for k, v in g.items() if not v),
            ]
        )
    head = ["critic", "usable", "raw detections", "backed detections", "high finding on clean",
            "findings", "unsupported", "gates"]  # fmt: skip
    return table(head, rows)


def others(runs: list[dict[str, Any]], label: str, pick: Any) -> str:
    rows = [
        [r["run"][:16], r["arm"], r["package"], r.get("temperature"), r.get("decision"),
         r.get("decision_correct"), len(r.get("escalations", [])), r["wall_seconds"]]
        for r in runs
        if pick(r)
    ]  # fmt: skip
    head = ["run", "arm", "package", "temperature", "decision", "correct", "escalations", "seconds"]
    return f"### {label}\n\n" + table(head, rows)


def main() -> None:
    ev = json.loads(Path(sys.argv[1]).read_text())
    keys = load_keys(Path("config/assess/answer-keys.yaml"))
    main_runs = [r for r in ev["runs"] if r.get("set") == "main"]
    print("### Decisions (temperature 0)\n")
    print(decisions(main_runs) + "\n")
    print("### Totals per arm (temperature 0)\n")
    print(arm_totals(main_runs, keys) + "\n")
    print("### Specialist and critic contributions\n")
    print(contributions(main_runs) + "\n")
    print("### Critic test (24 cases, scoring m41-v2)\n")
    print(critics(ev["critic"]) + "\n")
    print(others(ev["runs"], "Repeat and stochastic runs", lambda r: r.get("set") != "main"))


if __name__ == "__main__":
    main()
