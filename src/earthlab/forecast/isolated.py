"""Run the approved training template in a separate process with no network.

The process gets a scrubbed environment and a sandbox profile that refuses every network
call and every write outside its one output folder. Generated code never runs here: the
only program is the template in this repository. macOS only; elsewhere the run is refused.
"""

from __future__ import annotations

import os
import resource
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

SANDBOX = "/usr/bin/sandbox-exec"
PROFILE = """(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write* (subpath "{out}") (subpath "/private/var/folders") (literal "/dev/null"))
"""


class IsolationUnavailable(RuntimeError):
    """The sandbox is missing, so nothing was run."""


@dataclass(frozen=True)
class IsolatedRun:
    exit_code: int
    wall_seconds: float
    peak_rss_mb: float
    output_tail: str


def run_isolated(
    python: Path, program: Path, out: Path, args: list[str], timeout_seconds: float, threads: int
) -> IsolatedRun:
    if shutil.which(SANDBOX) is None:
        raise IsolationUnavailable(f"{SANDBOX} is not available")
    out = out.resolve()
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(out),
        "TMPDIR": str(out),
        "OMP_NUM_THREADS": str(threads),
        "MKL_NUM_THREADS": str(threads),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    command = [SANDBOX, "-p", PROFILE.format(out=out), str(python), "-I", str(program), *args]
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    started = time.perf_counter()
    with (out / "process.log").open("w", encoding="utf-8") as log:
        done = subprocess.run(  # noqa: S603 - fixed sandbox, fixed template, no shell
            command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
            timeout=timeout_seconds, close_fds=False,
        )  # fmt: skip
    wall = time.perf_counter() - started
    peak = max(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss, before)
    tail = (out / "process.log").read_text(encoding="utf-8")[-600:]
    return IsolatedRun(done.returncode, round(wall, 2), round(peak / 2**20, 1), tail)


def python_for_training() -> Path:
    """The isolated environment, named by the operator. Its absence is a clear refusal."""
    value = os.environ.get("EARTHLAB_TRAIN_PYTHON")
    if not value or not Path(value).is_file():
        raise IsolationUnavailable("set EARTHLAB_TRAIN_PYTHON to the pinned training environment")
    return Path(value)
