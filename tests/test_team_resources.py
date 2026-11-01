"""Resource requests: the order cannot be skipped, and a secret reaches one process only."""

from __future__ import annotations

import http.server
import json
import socket
import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from earthlab.team import fetch_job
from earthlab.team.broker import Broker, PreapprovedSource, covering, load_policy, read_secret
from earthlab.team.resources import (
    APPROVAL_FILE,
    OPERATOR_KEY_ENV,
    RequestRefused,
    ResourceDesk,
    ResourceRequestV1,
    large_assets,
)

KEY = "test-operator-key"
TOKEN = "mock-token-value-123"
BODY = b"month,area\n2015-09,1\n"
EXPIRES = datetime.now(UTC) + timedelta(days=1)


class Mock(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "https://example.com/")
            self.end_headers()
            return
        if self.path == "/keyed" and self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.send_response(401)
            self.end_headers()
            return
        body = b"#!/bin/sh\necho hi\n" if self.path == "/script" else BODY * 8
        kind = "text/html" if self.path == "/html" else "text/csv"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        return


@pytest.fixture
def server() -> Iterator[str]:
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Mock)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def operator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, KEY)


def request(url: str = "https://data.example.org/a.csv", **changes: Any) -> ResourceRequestV1:
    base: dict[str, Any] = {
        "request_id": "req-1",
        "parent_task_id": "lead.data",
        "purpose": "Compare QA gates with a second table.",
        "asset": "mock quality table",
        "url": url,
        "max_bytes": 4096,
        "content_types": ("text/csv",),
        "license_terms": "mock terms for a test",
        "expires_utc": EXPIRES,
        "scientific_need": "A second table lets the Lead check the gate.",
        "risk": "Low; a small public table.",
    }
    return ResourceRequestV1.model_validate({**base, **changes})


def endorsed(desk: ResourceDesk, req: ResourceRequestV1) -> None:
    desk.open(req)
    desk.review(req.request_id, "geospatial_engineer", "muse-glimmer", True, "needed")
    desk.review(req.request_id, "product_manager", "muse-glimmer", True, "in scope")


def trace_text(tmp_path: Path, name: str = "req-1") -> str:
    return (tmp_path / "requests" / name / "trace.jsonl").read_text(encoding="utf-8")


def test_the_full_route_fetches_with_the_secret_in_one_process(tmp_path: Path, server: str) -> None:
    desk = ResourceDesk(tmp_path)
    req = request(f"{server}/keyed", credential_name="MOCK_API_TOKEN")
    endorsed(desk, req)
    assert desk.view("req-1").status == "pm_endorsed"
    desk.decide("req-1", True, KEY, "owner")
    view = Broker(desk, tmp_path).fetch_approved("req-1", {"EARTHLAB_SECRET_MOCK_API_TOKEN": TOKEN})
    assert view.status == "fetched" and view.fetched is not None
    assert view.fetched["bytes"] == len(BODY) * 8
    kept = tmp_path / "staging" / str(view.fetched["sha256"])
    assert kept.read_bytes() == BODY * 8 and not kept.stat().st_mode & 0o222
    everything = "".join(p.read_text("utf-8") for p in tmp_path.rglob("*.json*"))
    assert TOKEN not in everything and KEY not in everything


def test_a_step_cannot_be_skipped(tmp_path: Path) -> None:
    desk = ResourceDesk(tmp_path)
    desk.open(request())
    with pytest.raises(RequestRefused):
        desk.review("req-1", "product_manager", "m", True, "skip the Lead")
    with pytest.raises(RequestRefused):
        desk.decide("req-1", True, KEY, "owner")
    with pytest.raises(RequestRefused):
        Broker(desk, tmp_path).fetch_approved("req-1")


def test_a_refusal_ends_the_request(tmp_path: Path) -> None:
    desk = ResourceDesk(tmp_path)
    desk.open(request())
    view = desk.review("req-1", "geospatial_engineer", "m", False, "not needed")
    assert view.status == "refused"
    with pytest.raises(RequestRefused):
        desk.review("req-1", "geospatial_engineer", "m", True, "again")


def test_a_wrong_key_changes_nothing_and_is_recorded(tmp_path: Path) -> None:
    desk = ResourceDesk(tmp_path)
    endorsed(desk, request())
    with pytest.raises(RequestRefused):
        desk.decide("req-1", True, "guess", "owner")
    assert desk.view("req-1").status == "pm_endorsed"
    assert "resource_key_refused" in trace_text(tmp_path)
    assert not (tmp_path / "requests" / "req-1" / APPROVAL_FILE).exists()


def test_no_operator_key_means_no_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(OPERATOR_KEY_ENV)
    desk = ResourceDesk(tmp_path)
    endorsed(desk, request())
    with pytest.raises(RequestRefused):
        desk.decide("req-1", True, "", "owner")


def test_a_denied_download_stays_denied(tmp_path: Path, server: str) -> None:
    desk = ResourceDesk(tmp_path)
    endorsed(desk, request(f"{server}/data"))
    assert desk.decide("req-1", False, KEY, "owner", "not now").status == "denied"
    with pytest.raises(RequestRefused):
        Broker(desk, tmp_path).fetch_approved("req-1")
    with pytest.raises(RequestRefused):
        desk.decide("req-1", True, KEY, "owner")
    assert not (tmp_path / "staging").exists()


def test_an_edited_approval_is_refused(tmp_path: Path, server: str) -> None:
    desk = ResourceDesk(tmp_path)
    endorsed(desk, request(f"{server}/data"))
    desk.decide("req-1", False, KEY, "owner")
    path = tmp_path / "requests" / "req-1" / APPROVAL_FILE
    saved = json.loads(path.read_text("utf-8"))
    saved["approved"] = True
    path.write_text(json.dumps(saved), "utf-8")
    with pytest.raises(RequestRefused):
        desk.authorized("req-1")


def test_a_forged_approval_with_another_key_is_refused(tmp_path: Path, server: str) -> None:
    desk = ResourceDesk(tmp_path)
    endorsed(desk, request(f"{server}/data"))
    desk.decide("req-1", True, KEY, "owner")
    path = tmp_path / "requests" / "req-1" / APPROVAL_FILE
    saved = json.loads(path.read_text("utf-8"))
    saved["signature"] = "0" * 64
    path.write_text(json.dumps(saved), "utf-8")
    with pytest.raises(RequestRefused, match="signature"):
        desk.authorized("req-1")
    assert "resource_blocked" in trace_text(tmp_path)


def test_an_approval_does_not_outlive_its_request(tmp_path: Path, server: str) -> None:
    desk = ResourceDesk(tmp_path)
    endorsed(desk, request(f"{server}/data"))
    desk.decide("req-1", True, KEY, "owner")
    with pytest.raises(RequestRefused, match="expired"):
        desk.authorized("req-1", at=EXPIRES + timedelta(seconds=1))


def test_a_missing_credential_fails_closed(tmp_path: Path, server: str) -> None:
    desk = ResourceDesk(tmp_path)
    endorsed(desk, request(f"{server}/keyed", credential_name="MOCK_API_TOKEN"))
    desk.decide("req-1", True, KEY, "owner")
    view = Broker(desk, tmp_path).fetch_approved("req-1", {})
    assert view.status == "failed" and "credential_required" in str(view.reason)


@pytest.mark.parametrize(
    ("path", "max_bytes", "why"),
    [
        ("/data", 10, "CapExceeded"),
        ("/html", 4096, "content type"),
        ("/redirect", 4096, "302"),
        ("/script", 4096, "executable"),
    ],
)
def test_a_transfer_outside_its_bounds_leaves_nothing(
    tmp_path: Path, server: str, path: str, max_bytes: int, why: str
) -> None:
    desk = ResourceDesk(tmp_path)
    endorsed(desk, request(f"{server}{path}", max_bytes=max_bytes))
    desk.decide("req-1", True, KEY, "owner")
    view = Broker(desk, tmp_path).fetch_approved("req-1")
    assert view.status == "failed" and why in str(view.reason)
    assert not list((tmp_path / "staging").glob("*"))


def test_the_same_content_is_kept_once(tmp_path: Path, server: str) -> None:
    desk = ResourceDesk(tmp_path)
    broker = Broker(desk, tmp_path)
    policy = [PreapprovedSource("127.0.0.1", "mock terms for a test", 4096, EXPIRES)]
    first = broker.fetch_preapproved(request(f"{server}/data"), policy)
    second = broker.fetch_preapproved(request(f"{server}/data", request_id="req-2"), policy)
    assert first.fetched is not None and second.fetched is not None
    assert not first.fetched["cached"] and second.fetched["cached"]
    assert "preapproved policy" in str(first.fetched["authority"])
    assert len(list((tmp_path / "staging").glob("*"))) == 1


def test_preapproval_never_covers_a_key_a_cost_or_a_larger_file() -> None:
    policy = [PreapprovedSource("data.example.org", "mock terms for a test", 4096, EXPIRES)]
    assert covering(request(), policy) is not None
    assert covering(request(credential_name="SOME_KEY"), policy) is None
    assert covering(request(expected_usd=1.0), policy) is None
    assert covering(request(max_bytes=8192), policy) is None
    assert covering(request(license_terms="other terms"), policy) is None
    assert covering(request("https://other.example.org/a.csv"), policy) is None
    old = [replace(policy[0], expires_utc=datetime(2020, 1, 1, tzinfo=UTC))]
    assert covering(request(), old) is None


def test_an_uncovered_public_request_goes_to_a_person(tmp_path: Path) -> None:
    with pytest.raises(RequestRefused):
        Broker(ResourceDesk(tmp_path), tmp_path).fetch_preapproved(request(), [])


def test_the_shipped_policy_preapproves_nothing() -> None:
    root = Path(__file__).resolve().parents[1]
    assert load_policy(root / "config" / "fetch" / "policy.yaml") == []


@pytest.mark.parametrize(
    "url",
    [
        "ftp://data.example.org/a",
        "http://data.example.org/a",
        "https://user:pw@data.example.org/a",
        "https://data.example.org/a?token=abc",
        "file:///etc/hosts",
    ],
)
def test_a_url_outside_the_rules_is_refused(url: str) -> None:
    with pytest.raises(ValidationError):
        request(url)


def test_a_request_cannot_hold_a_secret(tmp_path: Path) -> None:
    desk = ResourceDesk(tmp_path)
    with pytest.raises(RequestRefused, match="secret"):
        desk.open(request(purpose="Use Bearer abc123 for this transfer."))
    with pytest.raises(ValidationError):
        request(credential_name="sk-not-a-name")
    with pytest.raises(ValidationError):
        request(api_key="x")


def test_a_broken_request_trace_is_not_read(tmp_path: Path) -> None:
    desk = ResourceDesk(tmp_path)
    desk.open(request())
    path = tmp_path / "requests" / "req-1" / "trace.jsonl"
    path.write_text(path.read_text("utf-8").replace("req-1", "req-2", 1), "utf-8")
    with pytest.raises(RuntimeError):
        desk.view("req-1")


def test_secrets_are_read_only_under_their_prefix() -> None:
    assert read_secret("MOCK", {"EARTHLAB_SECRET_MOCK": "x", "MOCK": "y"}) == "x"
    assert read_secret("OTHER", {"OTHER": "y"}) is None


def scripted(*steps: Any) -> Any:
    from fake_client import ScriptedClient

    return ScriptedClient(list(steps))


def need(url: str = "https://data.example.org/a.csv") -> dict[str, Any]:
    return {
        "url": url,
        "asset": "mock table",
        "max_bytes": 4096,
        "content_types": ["text/csv"],
        "license_terms": "mock terms",
        "credential_name": "MOCK_API_TOKEN",
    }


ASKED = {"purpose": "Check the gate.", "scientific_need": "A second table.", "risk": "Low."}


def test_model_reviews_stop_at_the_person(tmp_path: Path) -> None:
    from fake_client import call

    from earthlab.team.request_flow import ASK, ENDORSE, run_request

    client = scripted(
        call(ASK, **ASKED),
        call(ENDORSE, endorse=True, note="Needed."),
        call(ENDORSE, endorse=True, note="In scope."),
    )
    view = run_request(tmp_path, client, need(), "req-1", "lead.data")
    assert view.status == "pm_endorsed" and len(view.reviewers) == 2
    assert view.request.url == need()["url"] and view.approval_sha256 is None
    assert [v.request.request_id for v in ResourceDesk(tmp_path).all()] == ["req-1"]


def test_a_model_cannot_set_the_url_or_add_approval(tmp_path: Path) -> None:
    from fake_client import call

    from earthlab.team.request_flow import ASK, run_request

    client = scripted(call(ASK, **ASKED, url="https://evil.example.org/x", approved=True))
    with pytest.raises(RequestRefused):
        run_request(tmp_path, client, need(), "req-1", "lead.data")


def test_a_lead_refusal_never_reaches_the_pm(tmp_path: Path) -> None:
    from fake_client import call

    from earthlab.team.request_flow import ASK, ENDORSE, run_request

    client = scripted(call(ASK, **ASKED), call(ENDORSE, endorse=False, note="Not needed."))
    view = run_request(tmp_path, client, need(), "req-1", "lead.data")
    assert view.status == "refused" and len(client.requests) == 2


def _large(**change: Any) -> dict[str, Any]:
    entry = large_assets()["prithvi-burnscars-weights"]
    return {
        "request_id": "weights", "parent_task_id": "tiers", "purpose": "A teacher tier.",
        "asset": entry["asset"], "url": entry["url"], "max_bytes": entry["max_bytes"],
        "expected_sha256": entry["sha256"], "content_types": entry["content_types"],
        "license_terms": entry["license_terms"], "scientific_need": "A costly teacher.",
        "risk": "Disk use.", "expires_utc": datetime.now(UTC) + timedelta(hours=1),
    } | change  # fmt: skip


def test_a_large_transfer_must_match_the_pinned_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    assert ResourceRequestV1(**_large()).max_bytes > 50_000_000
    for change in (
        {"url": "https://example.org/other.pt"},
        {"max_bytes": 3_000_000_000},
        {"expected_sha256": "0" * 64},
        {"expected_sha256": None},
    ):
        with pytest.raises(ValidationError):
            ResourceRequestV1(**_large(**change))


def test_a_pinned_digest_is_not_a_secret_but_a_token_in_text_still_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    desk = ResourceDesk(tmp_path)
    assert desk.open(ResourceRequestV1(**_large())).status == "proposed"
    named = _large(request_id="named", risk=f"Digest {_large()['expected_sha256']} is pinned.")
    assert desk.open(ResourceRequestV1(**named)).status == "proposed"
    leaked = _large(request_id="leak", purpose="Use sk-abcdefgh12345678 for this.")
    with pytest.raises(RequestRefused, match="shaped like a secret"):
        desk.open(ResourceRequestV1(**leaked))
    view = desk.review("named", "geospatial_engineer", "m", True, "Bearer abc123 is the key.")
    assert "abc123" not in json.dumps(list(desk._trace("named").records()))
    assert view.status == "lead_endorsed"


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.8", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1",
     "0.0.0.0", "224.0.0.1", "::1", "fe80::1%en0", "fc00::1", "::ffff:169.254.169.254"],
)  # fmt: skip
def test_an_internal_address_is_not_public(address: str) -> None:
    assert not fetch_job.is_public(address)


def test_a_public_address_is_public() -> None:
    assert fetch_job.is_public("93.184.216.34") and fetch_job.is_public("2606:2800:220:1::1")


def answer(*addresses: str) -> Any:
    return lambda *_args, **_kwargs: [(2, 1, 6, "", (a, 443)) for a in addresses]


def test_one_internal_answer_refuses_the_name() -> None:
    with pytest.raises(ValueError, match="not public"):
        fetch_job.public_only(answer("93.184.216.34", "10.0.0.8"))("x", 443)


def test_a_rebound_name_is_refused_at_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The guard is on the resolver, so the connection's own lookup is the one checked."""
    monkeypatch.setattr(socket, "getaddrinfo", answer("169.254.169.254"))
    job = {
        "url": "https://rebind.example/data", "domain": "rebind.example",
        "target": str(tmp_path / "out"), "content_types": ["text/csv"],
        "timeout_seconds": 2.0, "max_bytes": 64,
    }  # fmt: skip
    with pytest.raises(ValueError, match="not public"):
        fetch_job.fetch(job, "secret")
    assert not (tmp_path / "out").exists()


def test_https_on_a_loopback_literal_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", socket.getaddrinfo)  # restored after the test
    job = {
        "url": "https://127.0.0.1/data", "domain": "127.0.0.1",
        "target": str(tmp_path / "out"), "content_types": ["text/csv"],
        "timeout_seconds": 2.0, "max_bytes": 64,
    }  # fmt: skip
    with pytest.raises(ValueError, match="not public"):
        fetch_job.fetch(job, None)
