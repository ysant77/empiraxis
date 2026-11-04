"""Build the demonstration package e-m5-demo-v3 from the merged M5 evidence at a pinned commit.

Files are read with `git show COMMIT:PATH`, never from a working tree. The frozen benchmark
packages are not read or written.

Usage: python scripts/m41_package_demo.py --repo DIR --m5-ref SHA --out DIR
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from m41_package_store import Store

from earthlab.assess.m5_demo import DEMO_ID, build

M5_PACKAGE = "docs/m5/evidence/scientific_evidence_package_v1.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--m5-ref", required=True)
    ap.add_argument("--out", type=Path, default=Path("examples/assess/packages"))
    a = ap.parse_args()
    store = Store(Path("."), Path("."), a.repo, a.m5_ref)
    ref = a.m5_ref
    if len(ref) != 40:
        raise SystemExit("--m5-ref must be a full 40-character commit")

    def read(rel: str) -> bytes:
        return store.git_bytes(ref, rel)

    pkg = build(json.loads(read(M5_PACKAGE)), read, ref)
    path = a.out / f"{DEMO_ID}.json"
    path.write_text(json.dumps(pkg.model_dump(mode="json"), indent=1) + "\n")
    print(path, ref)


if __name__ == "__main__":
    main()
