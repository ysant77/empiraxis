"""Inbound peer authentication for the A2A endpoint.

The server stores SHA-256 digests of bearer tokens, never the tokens. A peer's token proves
who it is to this server and goes no further: no trace, record or engineer call carries it.
The Agent Card stays public, as discovery needs. Every RPC call needs a valid token.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterable
from dataclasses import dataclass

from starlette.authentication import AuthCredentials, SimpleUser
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

RUN_SCOPE = "earthlab.engineer.run"
MAX_BODY_BYTES = 64 * 1024


@dataclass(frozen=True)
class Peer:
    name: str
    token_sha256: str
    scopes: frozenset[str] = frozenset({RUN_SCOPE})


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PeerRegistry:
    def __init__(self, peers: Iterable[Peer]):
        self._peers = tuple(peers)

    def authenticate(self, token: str) -> Peer | None:
        """The peer that holds this token. Every entry is compared, in constant time."""
        digest = token_digest(token)
        found = None
        for peer in self._peers:
            if hmac.compare_digest(digest, peer.token_sha256):
                found = peer
        return found


def _bearer(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name == b"authorization":
            kind, _, token = value.decode("latin-1").partition(" ")
            return token.strip() if kind.lower() == "bearer" and token.strip() else None
    return None


def _body_fault(scope: Scope) -> Response | None:
    """Refuse a body with no declared length or above the limit, before the SDK reads it."""
    for name, value in scope["headers"]:
        if name == b"content-length":
            if value.isdigit() and int(value) <= MAX_BODY_BYTES:
                return None
            return JSONResponse({"error": "request body too large"}, status_code=413)
    return JSONResponse({"error": "content length required"}, status_code=411)


class PeerAuthMiddleware:
    """Guard one path: 401 without a valid token, 403 without the run scope."""

    def __init__(self, app: ASGIApp, registry: PeerRegistry, rpc_path: str):
        self._app = app
        self._registry = registry
        self._rpc_path = rpc_path

    def _fault(self, scope: Scope) -> Response | None:
        token = _bearer(scope)
        peer = None if token is None else self._registry.authenticate(token)
        if peer is None:
            headers = {"WWW-Authenticate": "Bearer"}
            return JSONResponse({"error": "unauthenticated"}, status_code=401, headers=headers)
        if RUN_SCOPE not in peer.scopes:
            return JSONResponse({"error": "missing scope"}, status_code=403)
        scope["user"] = SimpleUser(peer.name)
        scope["auth"] = AuthCredentials(sorted(peer.scopes))
        return _body_fault(scope)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == self._rpc_path:
            fault = self._fault(scope)
            if fault is not None:
                await fault(scope, receive, send)
                return
        await self._app(scope, receive, send)
