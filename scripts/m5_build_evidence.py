"""Reproduce the archived m5-evidence-4 package from its pinned source commit.

The archived file docs/m5/evidence/scientific_evidence_package_v1.json is frozen. This script
never writes it. It extracts the source commit with `git archive` into a temporary folder, runs
that commit's own builder there, writes the result to --out, and checks that the bytes equal the
archived file. The current package is m5-evidence-5 (scripts/m5_build_evidence_v2.py).

Usage: m5_build_evidence.py --out FILE [--commit SHA]   (run from the repository root)
Exit status: 0 if the bytes match, 1 if they differ, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

SOURCE_COMMIT = "78bd3fb13d958704e0d3d890c0ce3a562556f7ac"
ARCHIVED = Path("docs/m5/evidence/scientific_evidence_package_v1.json")
ARCHIVED_SHA256 = "b0ad01a1b7b4b0346edc5841b541747b34c773f62dfebbf8128357ab3dbe3497"
_RUN = (
    "import sys; sys.path.insert(0, 'src'); from pathlib import Path; "
    "from earthlab.m5.evidence import build, verify; pkg = build(Path.cwd()); "
    "assert verify(pkg); sys.stdout.write(pkg.model_dump_json(indent=2) + '\\n')"
)


def reproduce(repo: Path, out: Path, commit: str = SOURCE_COMMIT) -> str:
    """Build the v4 package at `commit` into `out` and return the SHA-256 of its bytes."""
    if out.resolve() == (repo / ARCHIVED).resolve():
        raise SystemExit(f"refusing to write the archived file {ARCHIVED}")
    with tempfile.TemporaryDirectory() as tmp:
        archive = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo), "archive", "--format=tar", commit],  # noqa: S607
            check=True,
            capture_output=True,
        ).stdout
        tar = Path(tmp) / "src.tar"
        tar.write_bytes(archive)
        with tarfile.open(tar) as t:
            t.extractall(Path(tmp) / "tree", filter="data")
        body = subprocess.run(  # noqa: S603
            [sys.executable, "-I", "-c", _RUN],
            cwd=Path(tmp) / "tree",
            check=True,
            capture_output=True,
        ).stdout
    out.write_bytes(body)
    return hashlib.sha256(body).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--commit", default=SOURCE_COMMIT)
    a = ap.parse_args()
    sha = reproduce(Path.cwd(), a.out, a.commit)
    same = sha == ARCHIVED_SHA256
    print(f"{a.out} sha256={sha} {'matches' if same else 'DIFFERS from'} {ARCHIVED}")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
