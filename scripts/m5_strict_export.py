"""Write a standards-compliant derived export of the primary M5-C result.

The primary file docs/m5/results/m5_c_v1.json stays byte-identical (it holds NaN tokens, which
are not valid JSON). This export keeps every number, sets each undefined value to null and lists
the path and reason of each one.

Usage: uv run python scripts/m5_strict_export.py   (run from the repository root)
Output: docs/m5/results/m5_c_v1.strict_v1.json
"""

from __future__ import annotations

import json
from pathlib import Path

from earthlab.digest import file_digest
from earthlab.m5 import strict_json as sj

SOURCE = Path("docs/m5/results/m5_c_v1.json")
OUT = Path("docs/m5/results/m5_c_v1.strict_v1.json")
EXPORT_VERSION = "m5-strict-export-1"
REASONS = {k: "no issue outside the abstention band (coverage 0): rate undefined"
           for k in ("error_rate", "random_error_rate", "calibration_gap")}  # fmt: skip


def build() -> dict[str, object]:
    data, missing = sj.sanitize(json.loads(SOURCE.read_text()), REASONS)
    return {"export_version": EXPORT_VERSION, "source_file": SOURCE.name,
            "source_sha256": file_digest(SOURCE), "missing_value_reasons": missing,
            "data": data}  # fmt: skip


if __name__ == "__main__":
    out = build()
    OUT.write_text(sj.dumps(out, indent=1, sort_keys=True) + "\n")
    print(OUT, "missing", len(out["missing_value_reasons"]))  # type: ignore[arg-type]
