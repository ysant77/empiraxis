"""Resource requests: specialist -> Geospatial Lead -> PM -> Human Director, in that order.

A model can propose or endorse. Only a person holding the operator key can approve, and the
decision is a signed record bound to the exact request bytes. The controller checks that
record before any transfer. Each request has its own hash-chained trace; its state is
computed from that trace. A request names a credential; it never holds one.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import Field, field_validator, model_validator

from earthlab.contracts import Strict
from earthlab.digest import payload_digest
from earthlab.trace import RunTrace

OPERATOR_KEY_ENV = "EARTHLAB_OPERATOR_KEY"
MAX_BYTES = 50_000_000
LARGE_ASSETS = Path("config/fetch/large-assets.yaml")
REQUESTS_DIR = "requests"
APPROVAL_FILE = "approval.json"
Status = Literal[
    "proposed", "lead_endorsed", "pm_endorsed", "approved", "denied", "refused", "fetched", "failed"
]
ReviewRole = Literal["geospatial_engineer", "product_manager"]
_NEXT: dict[str, tuple[str, str]] = {
    "geospatial_engineer": ("proposed", "lead_endorsed"),
    "product_manager": ("lead_endorsed", "pm_endorsed"),
}
_SECRET_SHAPES = re.compile(
    r"sk-[A-Za-z0-9]{8,}|Bearer\s+\S+|[0-9a-fA-F]{32,}|[A-Za-z0-9+/]{40,}={0,2}"
)


class RequestRefused(ValueError):
    """The request or the step breaks a rule. Nothing changed."""


def large_assets(path: Path = LARGE_ASSETS) -> dict[str, dict[str, Any]]:
    """The catalogue of pinned large assets. Being listed grants nothing."""
    if not path.is_file():
        return {}
    assets: dict[str, dict[str, Any]] = yaml.safe_load(path.read_text("utf-8"))["assets"]
    return assets


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def holds_secret(text: str, request: ResourceRequestV1) -> bool:
    """Secret-shaped text, other than this request's own public pinned digest."""
    pinned = request.expected_sha256 if request.max_bytes > MAX_BYTES else None
    return bool(_SECRET_SHAPES.search(text.replace(pinned, "") if pinned else text))


class ResourceRequestV1(Strict):
    """Exact bounds of one transfer. The human decision is bound to these bytes."""

    schema_version: Literal["1"] = "1"
    request_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")
    parent_task_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")
    actor: Literal["data_specialist"] = "data_specialist"
    purpose: str = Field(min_length=5, max_length=300)
    asset: str = Field(min_length=3, max_length=120)
    url: str = Field(max_length=500)
    max_bytes: int = Field(gt=0)
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content_types: tuple[str, ...] = Field(min_length=1, max_length=4)
    license_terms: str = Field(min_length=3, max_length=200)
    credential_name: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,40}$")
    expected_usd: float = Field(default=0.0, ge=0)
    operations: tuple[Literal["http_get"], ...] = ("http_get",)
    expires_utc: datetime
    alternatives: tuple[str, ...] = Field(default=(), max_length=4)
    scientific_need: str = Field(min_length=5, max_length=300)
    risk: str = Field(min_length=3, max_length=200)

    @field_validator("url")
    @classmethod
    def _bounded_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.username or parts.password or parts.query:
            raise ValueError("a URL may not carry a user, password or query")
        if parts.scheme == "https" and parts.hostname:
            return value
        if parts.scheme == "http" and parts.hostname and _is_loopback(parts.hostname):
            return value  # the local mock server only
        raise ValueError("only https, or http on a loopback mock, is allowed")

    @model_validator(mode="after")
    def _within_cap(self) -> ResourceRequestV1:
        """Above the cap, the exact URL, size and digest must be in the catalogue."""
        if self.max_bytes <= MAX_BYTES:
            return self
        for entry in large_assets().values():
            if (entry["url"], entry["max_bytes"], entry["sha256"]) == (
                self.url, self.max_bytes, self.expected_sha256,
            ):  # fmt: skip
                return self
        raise ValueError("a transfer above the cap must match a pinned catalogue entry")

    @property
    def domain(self) -> str:
        return str(urlsplit(self.url).hostname)

    def sha256(self) -> str:
        return payload_digest(self.model_dump(mode="json"))


class ResourceApprovalV1(Strict):
    """A human decision. The signature needs the operator key, which no model can hold."""

    request_id: str
    request_sha256: str
    approved: bool
    approver: str
    decided_at_utc: datetime
    note: str = Field(default="", max_length=300)
    signature: str = ""

    def body(self) -> bytes:
        data = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(data, sort_keys=True).encode()


def sign(approval: ResourceApprovalV1, key: str) -> str:
    return hmac.new(key.encode(), approval.body(), hashlib.sha256).hexdigest()


def operator_key() -> str | None:
    """The key from the operator's environment. None means no approval control exists."""
    return os.environ.get(OPERATOR_KEY_ENV) or None


def key_matches(offered: str) -> bool:
    key = operator_key()
    return key is not None and secrets.compare_digest(offered.encode(), key.encode())


@dataclass
class RequestView:
    request: ResourceRequestV1
    status: Status
    reviewers: list[str] = field(default_factory=list)
    approval_sha256: str | None = None
    records: int = 0
    head: str = ""
    fetched: dict[str, Any] | None = None
    reason: str | None = None


def fold_request(entries: list[dict[str, Any]]) -> RequestView:
    first = entries[0]["data"]["request"]
    view = RequestView(ResourceRequestV1.model_validate(first), "proposed")
    for entry in entries[1:]:
        data = entry["data"]
        if entry["event"] == "resource_reviewed":
            view.reviewers.append(f"{data['role']}: {data['reviewer']}")
            view.status = data["status"]
            view.reason = data.get("note")
        elif entry["event"] == "resource_decided":
            view.status = "approved" if data["approved"] else "denied"
            view.approval_sha256 = data["approval_sha256"]
        elif entry["event"] == "resource_fetched":
            view.status, view.fetched = "fetched", data
        elif entry["event"] == "resource_blocked":
            view.status, view.reason = "failed", data["reason"]
    view.records, view.head = len(entries), str(entries[-1]["hash"])
    return view


class ResourceDesk:
    """The only code that moves a request. Every step is checked and traced."""

    def __init__(self, runs_dir: Path):
        self.root = runs_dir / REQUESTS_DIR

    def _trace(self, request_id: str) -> RunTrace:
        return RunTrace(self.root / request_id / "trace.jsonl")

    def view(self, request_id: str) -> RequestView:
        trace = self._trace(request_id)
        trace.verify()
        return fold_request(list(trace.records()))

    def all(self) -> list[RequestView]:
        if not self.root.is_dir():
            return []
        folders = sorted(p.parent.name for p in self.root.glob("*/trace.jsonl"))
        return [self.view(name) for name in folders if not name.endswith(".models")]

    def open(self, request: ResourceRequestV1) -> RequestView:
        dumped = request.model_dump(mode="json")
        pinned = ("url", "expected_sha256") if request.max_bytes > MAX_BYTES else ()
        scanned = {k: v for k, v in dumped.items() if k not in pinned}  # exact catalogue values
        if holds_secret(json.dumps(scanned), request):
            raise RequestRefused("the request holds text shaped like a secret")
        if (self.root / request.request_id).exists():
            raise RequestRefused("this request ID exists")
        trace = self._trace(request.request_id)
        trace.append(
            "resource_requested", "data_specialist", request=dumped, request_sha256=request.sha256()
        )
        return self.view(request.request_id)

    def review(
        self, request_id: str, role: ReviewRole, reviewer: str, endorse: bool, note: str
    ) -> RequestView:
        """One endorsement, in order. A role cannot act out of turn or act twice."""
        view = self.view(request_id)
        before, after = _NEXT[role]
        if view.status != before:
            raise RequestRefused(f"{role} cannot act on a request in state {view.status}")
        kept = "note withheld: it held text shaped like a secret"
        kept = kept if holds_secret(note, view.request) else note[:300]
        self._trace(request_id).append(
            "resource_reviewed", role, role=role, reviewer=reviewer, endorsed=endorse,
            status=after if endorse else "refused", note=kept,
        )  # fmt: skip
        return self.view(request_id)

    def decide(
        self, request_id: str, approve: bool, offered_key: str, approver: str, note: str = ""
    ) -> RequestView:
        """The Human Director's step. A wrong key changes nothing and is recorded."""
        view = self.view(request_id)
        if not key_matches(offered_key):
            self._trace(request_id).append("resource_key_refused", "approval_gate")
            raise RequestRefused("the operator key is not valid")
        if view.status != "pm_endorsed":
            raise RequestRefused(f"a request in state {view.status} cannot be decided")
        approval = ResourceApprovalV1(
            request_id=request_id, request_sha256=view.request.sha256(), approved=approve,
            approver=approver, decided_at_utc=datetime.now(UTC), note=note,
        )  # fmt: skip
        signed = approval.model_copy(update={"signature": sign(approval, offered_key)})
        path = self.root / request_id / APPROVAL_FILE
        try:
            with path.open("x", encoding="utf-8") as out:  # the first decision stands
                out.write(signed.model_dump_json(indent=2))
        except FileExistsError:
            raise RequestRefused("this request is already decided") from None
        self._trace(request_id).append(
            "resource_decided", "human_director", approved=approve, approver=approver,
            approval_sha256=payload_digest(signed.model_dump(mode="json")),
        )  # fmt: skip
        return self.view(request_id)

    def authorized(self, request_id: str, at: datetime | None = None) -> ResourceRequestV1:
        """The exact request, if a valid signed approval covers it now. Else raise."""
        view = self.view(request_id)
        problem = self._problem(view, at or datetime.now(UTC))
        if problem is not None:
            self._trace(request_id).append("resource_blocked", "approval_gate", reason=problem)
            raise RequestRefused(problem)
        return view.request

    def _problem(self, view: RequestView, now: datetime) -> str | None:
        if view.status != "approved":
            return f"the request is {view.status}, not approved"
        path = self.root / view.request.request_id / APPROVAL_FILE
        approval = ResourceApprovalV1.model_validate_json(path.read_text(encoding="utf-8"))
        key = operator_key()
        if key is None:
            return "no operator key is set, so the approval cannot be checked"
        if not secrets.compare_digest(sign(approval, key), approval.signature):
            return "the approval signature does not match"
        if approval.request_sha256 != view.request.sha256() or not approval.approved:
            return "the approval does not cover this request"
        if view.request.expires_utc <= now:
            return "the approval has expired"
        return None

    def record_fetch(self, request_id: str, **data: Any) -> RequestView:
        self._trace(request_id).append("resource_fetched", "runtime", **data)
        return self.view(request_id)

    def record_failure(self, request_id: str, reason: str) -> RequestView:
        self._trace(request_id).append("resource_blocked", "runtime", reason=reason[:300])
        return self.view(request_id)
