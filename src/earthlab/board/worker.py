"""One detached process for one queued run: claim it, keep a heartbeat, record how it ended.

The board state says whether the process finished. The scientific outcome stays in the
trace, so a worker that exits cleanly never turns into a success on any view.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Mapping
from pathlib import Path

from earthlab.board.execute import execute
from earthlab.board.store import BOARD_FILE, Board
from earthlab.llm.providers import load_providers
from earthlab.runtime import open_workspace

BEAT_SECONDS = 5.0
DATA_DIR = Path("data/nea")
PROVIDERS = Path("config/providers.yaml")
RUNTIME_ENV = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE", "VIRTUAL_ENV")
log = logging.getLogger(__name__)


def worker_env(
    run_id: str, runs_dir: Path, source: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The runtime settings, plus only the key the run's own provider names.

    Operator keys, broker secrets and every other credential stay out of the worker.
    """
    origin = os.environ if source is None else source
    names = list(RUNTIME_ENV)
    entry = Board(runs_dir / BOARD_FILE).get(run_id)
    config = load_providers(PROVIDERS).get(entry.spec.provider) if entry else None
    if config is not None and config.enabled and config.api_key_env:
        names.append(config.api_key_env)
    return {name: origin[name] for name in names if name in origin}


def spawn(run_id: str, runs_dir: Path) -> int:
    """Start the worker. The request stays in the board, not in argv.

    close_fds=False selects posix_spawn: on macOS a fork from the threaded Streamlit server
    crashes the child before exec (exit -11). Python opens files as non-inheritable, so no
    server socket reaches the worker. The worker leaves this session itself, in main().
    """
    runs_dir.mkdir(parents=True, exist_ok=True)
    with open(runs_dir / f"{run_id}.worker.log", "ab") as output:
        process = subprocess.Popen(  # noqa: S603 - fixed module; run_id comes from the board
            [sys.executable, "-m", "earthlab.board.worker", run_id, "--runs-dir", str(runs_dir)],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=worker_env(run_id, runs_dir),
            close_fds=False,
        )
    return process.pid


def _heartbeat(board: Board, run_id: str, stop: threading.Event) -> None:
    while not stop.wait(BEAT_SECONDS):
        board.beat(run_id)


def work(run_id: str, runs_dir: Path) -> int:
    board = Board(runs_dir / BOARD_FILE)
    if not board.claim(run_id, os.getpid()):
        return 0
    entry = board.get(run_id)
    if entry is None:
        return 1
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    stop = threading.Event()
    threading.Thread(target=_heartbeat, args=(board, run_id, stop), daemon=True).start()
    try:
        execute(entry.spec, run_dir, open_workspace(DATA_DIR), PROVIDERS, DATA_DIR)
    except Exception as exc:
        log.exception("run %s failed", run_id)
        board.end(run_id, "failed", type(exc).__name__)
        return 1
    finally:
        stop.set()
    board.end(run_id, "finished")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()
    with contextlib.suppress(PermissionError):  # already a group leader when run by hand
        os.setsid()
    logging.basicConfig(level=logging.WARNING)
    return work(args.run_id, args.runs_dir)


if __name__ == "__main__":
    raise SystemExit(main())
