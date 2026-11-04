"""Write docs/m5/evidence/scientific_evidence_package_v1.json from committed M5 artifacts.

Usage: m5_build_evidence.py   (run from the repository root)
"""

from __future__ import annotations

from pathlib import Path

from earthlab.m5.evidence import build, verify

if __name__ == "__main__":
    pkg = build(Path.cwd())
    assert verify(pkg)
    out = Path("docs/m5/evidence/scientific_evidence_package_v1.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(pkg.model_dump_json(indent=2) + "\n")
    print(f"{out} sha256={pkg.package_sha256} assets={len(pkg.assets)}")
