"""Sequential serving: Muse stays loaded; at most one small model runs beside it.

Before a role uses a server, code reads the served file name from `/props` and compares it
with the checkpoint registry. A mismatch stops the run. Load and unload times are recorded,
so the cost of switching models is part of the evidence.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Protocol

import httpx

from earthlab.harness.identity import CheckpointV1


class IdentityError(RuntimeError):
    """The server does not serve the checkpoint that the registry names."""


def served_file(base_url: str, client: httpx.Client | None = None) -> str:
    http = client or httpx.Client(timeout=10)
    root = base_url.rstrip("/").removesuffix("/v1")
    path = str(http.get(f"{root}/props").json().get("model_path") or "")
    return Path(path).name


def verify_identity(base_url: str, ckpt: CheckpointV1, client: httpx.Client | None = None) -> str:
    name = served_file(base_url, client)
    if name != ckpt.file:
        raise IdentityError(f"{ckpt.provider}: server has {name!r}, registry has {ckpt.file!r}")
    return name


class Server(Protocol):
    def ensure(self, provider: str) -> float: ...

    def stop(self) -> float: ...


class SideServer:
    """One llama-server process on a fixed port. `ensure` returns the seconds it took."""

    def __init__(self, models: dict[str, Path], registry: dict[str, CheckpointV1], port: int):
        self.models, self.registry, self.port = models, registry, port
        self.current: str | None = None
        self._proc: subprocess.Popen[bytes] | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def ensure(self, provider: str) -> float:
        if provider == self.current:
            return 0.0
        started = time.perf_counter()
        self.stop()
        path = self.models[provider]
        binary = shutil.which("llama-server")
        if binary is None:
            raise FileNotFoundError("llama-server is not on PATH")
        self._proc = subprocess.Popen(  # noqa: S603 - fixed binary and arguments, no shell
            [
                binary,
                "-m",
                str(path),
                "-a",
                provider,
                "-c",
                "16384",
                "-np",
                "1",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--jinja",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._wait_ready()
        verify_identity(self.base_url, self.registry[provider])
        self.current = provider
        return round(time.perf_counter() - started, 2)

    def _wait_ready(self, limit: float = 180.0) -> None:
        deadline = time.monotonic() + limit
        root = self.base_url.removesuffix("/v1")
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{root}/health", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise TimeoutError(f"side server on port {self.port} did not become ready")

    def stop(self) -> float:
        if self._proc is None:
            return 0.0
        started = time.perf_counter()
        self._proc.terminate()
        self._proc.wait(timeout=60)
        self._proc, self.current = None, None
        return round(time.perf_counter() - started, 2)
