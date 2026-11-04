"""Re-check recorded m41-v2 runs with the m41-v3 number rule. Calls no model.

The recorded result files are not changed. For each run, the script lists the numbers in the
recorded findings and plans that the m41-v2 rule (decimals only) passed and the m41-v3 rule
(decimals and integer measurements) does not. The output is a separate evaluation file.

Usage: python scripts/m41_recheck_numbers.py RUNS_DIR [RUNS_DIR ...] --out FILE
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from earthlab.assess.checks import ungrounded_numbers
from earthlab.assess.contracts import EvidencePackageV1
from earthlab.assess.numbers import DECIMAL

PACKAGES = Path("examples/assess/packages")


def texts(role: str, output: dict[str, Any]) -> list[tuple[str, str]]:
    """(label, text) pairs that the number check reads: finding claims, plan and claims."""
    out = [(f"{role} finding {f['id']}", f["claim"]) for f in output.get("findings", [])]
    if "plan" in output:
        out += [(f"{role} plan", output["plan"])]
        out += [(f"{role} claim {i}", c) for i, c in enumerate(output.get("claims", []))]
    return out


def recheck(run: Path, pkgs: dict[str, EvidencePackageV1]) -> dict[str, Any]:
    result = json.loads((run / "result.json").read_text())
    pkg = pkgs[result["package_id"]]
    new: list[dict[str, Any]] = []
    for role, entry in result["roles"].items():
        for label, text in texts(role, entry.get("output") or {}):
            decimals = set(DECIMAL.findall(text))
            loose = [n for n in ungrounded_numbers([text], pkg) if n not in decimals]
            if loose:
                new.append({"where": label, "numbers": loose})
    return {"run": run.name, "arm": result["arm"], "package": result["package_id"], "new": new}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    pkgs = {
        p.package_id: p
        for p in (
            EvidencePackageV1.model_validate_json(f.read_text())
            for f in sorted(PACKAGES.glob("*.json"))
        )
    }
    rows = [
        recheck(r, pkgs)
        for d in a.runs
        for r in sorted(d.iterdir())
        if (r / "result.json").exists()
    ]
    body = {
        "evaluation": "m41-v3 number rule on recorded m41-v2 runs (offline, no model call)",
        "runs": len(rows),
        "runs_with_new_ungrounded_numbers": sum(bool(r["new"]) for r in rows),
        "rows": rows,
    }
    a.out.write_text(json.dumps(body, indent=1) + "\n")
    print(body["runs"], body["runs_with_new_ungrounded_numbers"])


if __name__ == "__main__":
    main()
