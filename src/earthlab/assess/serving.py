"""Sequential serving: Muse stays loaded; at most one small model runs beside it.

Identity is checked twice. Before the side server starts a model, code computes the SHA-256
of the exact file it passes to the process and compares it with the registry. Before a role
uses a server, code reads the served file from `/props` and compares the name. For a server
that is already running (Muse), code hashes the file that `/props` names. A mismatch stops
the run. Digest time, load time and unload time are recorded, so these costs are evidence.
A digest is computed once per file per process (keyed by path, size and modification time).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
from pathlib import Path
from typing import Protocol

import httpx

from earthlab.harness.identity import CheckpointV1


class IdentityError(RuntimeError):
    """The server does not serve the checkpoint that the registry names."""


CHUNK = 1 << 24
_DIGESTS: dict[tuple[str, int, int], str] = {}


def served_path(base_url: str, client: httpx.Client | None = None) -> Path:
    http = client or httpx.Client(timeout=10)
    root = base_url.rstrip("/").removesuffix("/v1")
    return Path(str(http.get(f"{root}/props").json().get("model_path") or ""))


def served_file(base_url: str, client: httpx.Client | None = None) -> str:
    return served_path(base_url, client).name


def verify_file(path: Path, ckpt: CheckpointV1) -> dict[str, object]:
    """Hash the model file and compare it with the registry. Returns the record (no path)."""
    if path.name != ckpt.file:
        raise IdentityError(f"{ckpt.provider}: file {path.name!r}, registry has {ckpt.file!r}")
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    started = time.perf_counter()
    cached = key in _DIGESTS
    if not cached:
        digest = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(CHUNK):
                digest.update(chunk)
        _DIGESTS[key] = digest.hexdigest()
    if _DIGESTS[key] != ckpt.sha256:
        raise IdentityError(f"{ckpt.provider}: {path.name} SHA-256 differs from the registry")
    return {
        "provider": ckpt.provider,
        "file": ckpt.file,
        "sha256_verified": True,
        "bytes": stat.st_size,
        "digest_seconds": round(time.perf_counter() - started, 2),
        "cached": cached,
    }


def verify_served(base_url: str, ckpt: CheckpointV1, root: Path) -> dict[str, object]:
    """For a server that is already running: hash the file it reports in `/props`.

    llama-server reports the path as it was given; a relative path is resolved in `root`.
    """
    path = served_path(base_url)
    if not path.is_absolute():
        path = root / path
    return verify_file(path, ckpt)


def verify_identity(base_url: str, ckpt: CheckpointV1, client: httpx.Client | None = None) -> str:
    name = served_file(base_url, client)
    if name != ckpt.file:
        raise IdentityError(f"{ckpt.provider}: server has {name!r}, registry has {ckpt.file!r}")
    return name


class Server(Protocol):
    digests: dict[str, dict[str, object]]

    def ensure(self, provider: str) -> float: ...

    def stop(self) -> float: ...


class SideServer:
    """One llama-server process on a fixed port. `ensure` returns the seconds it took."""

    def __init__(self, models: dict[str, Path], registry: dict[str, CheckpointV1], port: int):
        self.models, self.registry, self.port = models, registry, port
        self.current: str | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self.digests: dict[str, dict[str, object]] = {}

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def ensure(self, provider: str) -> float:
        if provider == self.current:
            return 0.0
        started = time.perf_counter()
        self.stop()
        path = self.models[provider]
        self.digests[provider] = verify_file(path, self.registry[provider])
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
