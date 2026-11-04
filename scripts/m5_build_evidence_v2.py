"""Write docs/m5/evidence/scientific_evidence_package_v2.json (version m5-evidence-5).

The v4 file scientific_evidence_package_v1.json is never rewritten. Run from the repository root.
"""

from __future__ import annotations

from pathlib import Path

from earthlab.m5.evidence_v2 import build, verify

if __name__ == "__main__":
    pkg = build(Path.cwd())
    assert verify(pkg)
    out = Path("docs/m5/evidence/scientific_evidence_package_v2.json")
    out.write_text(pkg.model_dump_json(indent=2) + "\n")
    print(f"{out} sha256={pkg.package_sha256} assets={len(pkg.assets)}")
