"""Print who did each step of a saved run, from its trace. No model runs.

A step is credited to a model only when the trace records that model's checked proposal.

Run with:  uv run python scripts/demo_contributions.py examples/replay/<run>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from earthlab.harness.credit import steps


def main() -> int:
    run = Path(sys.argv[1])
    for who, what, detail in steps(run):
        print(f"{who:44} {what:18} {detail}")
    record = json.loads((run / "result.json").read_text("utf-8"))
    usage = record.get("usage") or {}
    print(
        f"\nmodel calls {usage.get('model_calls', 'not measured')}, "
        f"wall {usage.get('wall_seconds', 'not measured')} s, "
        f"code outcome {record.get('code_outcome')}, status {record.get('status')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
