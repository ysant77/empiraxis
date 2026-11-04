"""Shared parts of the M4.1 package builder: artifact store, source and fact records."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

M3_RUN = "20261103T061204Z-829fed"
NEA_RUN = "20261103T035551Z-95e7a3"
TL_RUN = "20261103T140243Z-40d596"
M5_PATHS = {
    "stage_t": "docs/m5/results/m5_ladder_stage_t.json",
    "i1": "docs/m5/results/m5_i1_stage_p_2015.json",
    "hls": "docs/m5/qa/hls_qa.json",
    "smap": "docs/m5/qa/smap_qa.json",
    "rain": "docs/m5/qa/rain_compare_early.json",
}
LIMITS = [
    "Historical validation only. Not a forecast of any future date.",
    "Not for health, safety or travel decisions.",
    "PM2.5 alone does not identify the cause of haze.",
]


class Store:
    """Reads artifacts once and remembers their digests."""

    def __init__(self, runs: Path, m4_runs: Path, repo: Path, m5_ref: str):
        self.runs, self.m4_runs, self.repo, self.m5_ref = runs, m4_runs, repo, m5_ref

    def run_file(self, run: str, name: str) -> tuple[Any, str, str]:
        raw = (self.runs / run / name).read_bytes()
        return json.loads(raw), hashlib.sha256(raw).hexdigest(), f"earthlab-e2e-runs/{run}/{name}"

    def m4_file(self, rel: str) -> tuple[Any, str, str]:
        raw = (self.m4_runs / rel).read_bytes()
        return json.loads(raw), hashlib.sha256(raw).hexdigest(), f"m4-runs/{rel}"

    def repo_file(self, rel: str) -> tuple[Any, str, str]:
        raw = Path(rel).read_bytes()  # this checkout
        return json.loads(raw), hashlib.sha256(raw).hexdigest(), rel

    def git_bytes(self, ref: str, rel: str) -> bytes:
        git = shutil.which("git") or "git"
        return subprocess.run(  # noqa: S603 - fixed git command on a pinned commit
            [git, "-C", str(self.repo), "show", f"{ref}:{rel}"], check=True, capture_output=True
        ).stdout

    def m5_file(self, rel: str) -> tuple[Any, str, str]:
        git = shutil.which("git") or "git"
        raw = subprocess.run(  # noqa: S603 - fixed git command on a pinned commit
            [git, "-C", str(self.repo), "show", f"{self.m5_ref}:{rel}"],
            check=True,
            capture_output=True,
        ).stdout
        return json.loads(raw), hashlib.sha256(raw).hexdigest(), f"m5@{self.m5_ref[:7]}:{rel}"


def src(sid: str, dataset: str, role: str, avail: str, origin: str, **kw: Any) -> dict[str, Any]:
    return {
        "id": sid,
        "dataset": dataset,
        "role": role,
        "availability": avail,
        "origin": origin,
        **kw,
    }


def fact(
    fid: str, statement: str, source: str, value: float | None = None, unit: str = ""
) -> dict[str, Any]:
    return {"id": fid, "statement": statement, "value": value, "unit": unit, "source": source}


def _row(table: list[dict[str, Any]], model: str) -> dict[str, Any]:
    return next(r for r in table if r["model"] == model)
