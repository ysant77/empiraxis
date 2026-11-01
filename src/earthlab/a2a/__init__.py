"""Experimental A2A adapter around the bounded Geospatial Engineer.

The adapter lets an authenticated peer start, read and cancel one engineer task over the
A2A JSON-RPC binding. It is an optional transport outside the controller: code here
derives the task's tools and datasets from the registered case, keeps the peer inside the
server's budget, and returns digests and verified finding IDs. It holds no provider
credentials and grants no tool permission.

Status: experimental. The official SDK client talks to this server over a local socket in
the tests. Nothing here claims A2A conformance. Tasks and idempotency records live in
memory, so a server restart loses them.

The modules that import the SDK need the `a2a` extra. `contracts` does not.
"""

from __future__ import annotations

PROTOCOL_VERSION = "1.0"
STATUS = "experimental"
