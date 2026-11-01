"""The execution broker: the only code that reads a credential, and only after approval.

The secret stays out of every prompt, trace, task file and event. It reaches one child
process, in that process's environment, for the length of one transfer. A preapproved
public transfer uses the same path with no credential. Network limits are enforced by the
fetch code, which refuses non-public addresses; the operating system does not isolate the
child process, so this broker is scoped to trusted local experimentation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from earthlab.team.fetch_job import TOKEN_ENV
from earthlab.team.resources import RequestRefused, RequestView, ResourceDesk, ResourceRequestV1

SECRET_PREFIX = "EARTHLAB_SECRET_"  # noqa: S105 - a variable name prefix, not a value
STAGING = "staging"
TIMEOUT_SECONDS = 30.0
_CHILD_ENV = ("PATH", "HOME", "TMPDIR", "SSL_CERT_FILE")


def read_secret(name: str, source: Mapping[str, str] | None = None) -> str | None:
    """The named secret from the operator's environment. Agents never call this."""
    return (os.environ if source is None else source).get(SECRET_PREFIX + name)


@dataclass(frozen=True)
class PreapprovedSource:
    """A public no-key source the human approved ahead of time, within fixed limits."""

    domain: str
    license_terms: str
    max_bytes: int
    expires_utc: datetime


def load_policy(path: Path) -> list[PreapprovedSource]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        PreapprovedSource(
            str(s["domain"]),
            str(s["license_terms"]),
            int(s["max_bytes"]),
            datetime.fromisoformat(str(s["expires_utc"])),
        )
        for s in raw.get("preapproved", [])
    ]


def covering(
    request: ResourceRequestV1, policy: list[PreapprovedSource], at: datetime | None = None
) -> PreapprovedSource | None:
    """The source that covers a no-key, no-cost request, or None: it goes to a person."""
    now = at or datetime.now(UTC)
    if request.credential_name is not None or request.expected_usd > 0:
        return None
    for source in policy:
        fits = request.max_bytes <= source.max_bytes and source.expires_utc > now
        same = request.domain == source.domain and request.license_terms == source.license_terms
        if same and fits:
            return source
    return None


def _run_child(job: dict[str, object], secret: str | None) -> dict[str, object]:
    env = {k: os.environ[k] for k in _CHILD_ENV if k in os.environ}
    if secret is not None:
        env[TOKEN_ENV] = secret
    done = subprocess.run(
        [sys.executable, "-m", "earthlab.team.fetch_job"],
        input=json.dumps(job) + "\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=TIMEOUT_SECONDS + 10,
        close_fds=False,  # posix_spawn: a fork from the threaded server crashes on macOS
    )
    lines = done.stdout.strip().splitlines()
    if not lines:
        return {"error": f"the fetch process exited with {done.returncode}"}
    reply: dict[str, object] = json.loads(lines[-1])
    return reply


class Broker:
    def __init__(self, desk: ResourceDesk, runs_dir: Path):
        self.desk = desk
        self.staging = runs_dir / STAGING

    def _job(self, request: ResourceRequestV1, target: Path) -> dict[str, object]:
        return {
            "url": request.url,
            "domain": request.domain,
            "target": str(target),
            "max_bytes": request.max_bytes,
            "expected_sha256": request.expected_sha256,
            "content_types": list(request.content_types),
            "timeout_seconds": TIMEOUT_SECONDS,
        }

    def _transfer(
        self, request: ResourceRequestV1, secret: str | None, authority: str
    ) -> RequestView:
        self.staging.mkdir(parents=True, exist_ok=True)
        part = self.staging / f"{request.request_id}.download"
        reply = _run_child(self._job(request, part), secret)
        if "error" in reply:
            part.unlink(missing_ok=True)
            return self.desk.record_failure(request.request_id, str(reply["error"]))
        digest = str(reply["sha256"])
        kept = self.staging / digest
        cached = kept.exists()
        if cached:
            part.unlink()
        else:
            shutil.move(part, kept)
            kept.chmod(0o440)
        manifest = {
            "asset": request.asset, "url": request.url, "sha256": digest,
            "bytes": reply["bytes"], "content_type": reply["content_type"],
            "license_terms": request.license_terms, "authority": authority, "cached": cached,
            "retrieved_at_utc": datetime.now(UTC).isoformat(),
        }  # fmt: skip
        return self.desk.record_fetch(request.request_id, **manifest)

    def fetch_approved(
        self, request_id: str, secrets_from: Mapping[str, str] | None = None
    ) -> RequestView:
        """Run a transfer a signed human approval covers. Everything else stops here."""
        request = self.desk.authorized(request_id)
        secret = None
        if request.credential_name is not None:
            secret = read_secret(request.credential_name, secrets_from)
            if secret is None:
                return self.desk.record_failure(
                    request_id, f"credential_required: {request.credential_name} is not set"
                )
        return self._transfer(request, secret, "signed human approval")

    def fetch_preapproved(
        self, request: ResourceRequestV1, policy: list[PreapprovedSource]
    ) -> RequestView:
        """A public transfer covered in advance. It needs no new interaction and is traced."""
        view = self.desk.open(request)
        source = covering(request, policy)
        if source is None:
            raise RequestRefused(
                "no preapproved source covers this; it goes to the PM and a person"
            )
        return self._transfer(view.request, None, f"preapproved policy: {source.domain}")
