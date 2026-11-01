"""The Agent Card and the ASGI application for the experimental A2A endpoint.

The card declares only what the adapter does: the JSON-RPC binding, no streaming, no push
notifications, bearer authentication and one skill. The caller chooses the listening
socket. The application opens none, and the tests bind 127.0.0.1 only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.constants import TransportProtocol
from starlette.applications import Starlette
from starlette.middleware import Middleware

from earthlab import __version__
from earthlab.a2a import PROTOCOL_VERSION
from earthlab.a2a.auth import RUN_SCOPE, PeerAuthMiddleware, PeerRegistry
from earthlab.a2a.contracts import REPORT_MEDIA_TYPE, REQUEST_MEDIA_TYPE
from earthlab.a2a.engineer import EngineerPort
from earthlab.a2a.executor import EngineerExecutor
from earthlab.a2a.handler import EngineerRequestHandler
from earthlab.a2a.ledger import Quota, RequestLedger
from earthlab.agent.budget import Budget
from earthlab.cases.tools import CaseLibrary

RPC_PATH = "/a2a"
_BEARER = "bearer"


@dataclass(frozen=True)
class AgentSettings:
    """What the operator fixes for one server. A peer can lower the budget, not raise it."""

    public_url: str
    runs_root: Path
    limit: Budget = field(default_factory=Budget)
    quota: Quota = field(default_factory=Quota)


def agent_card(public_url: str) -> AgentCard:
    """The public card. It names no case, tool, dataset, provider or credential."""
    scheme = SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="Bearer"))
    requirement = SecurityRequirement(schemes={_BEARER: StringList(list=[RUN_SCOPE])})
    skill = AgentSkill(
        id="bounded-geospatial-investigation",
        name="Bounded geospatial investigation (experimental)",
        description=(
            "Run one plan-reviewed investigation on one registered case. The server sets the "
            "tools, datasets and budget limits. The result holds digests and verified finding "
            "IDs, with no raster or scientific value."
        ),
        tags=["geospatial", "experimental", "verified-findings"],
        input_modes=[REQUEST_MEDIA_TYPE],
        output_modes=[REPORT_MEDIA_TYPE],
    )
    return AgentCard(
        name="Axiom EarthLab Geospatial Engineer (experimental)",
        description=(
            "Experimental A2A adapter around a bounded engineer. A deterministic verifier "
            "decides every finding. This adapter makes no claim of A2A conformance."
        ),
        version=__version__,
        supported_interfaces=[
            AgentInterface(
                url=f"{public_url.rstrip('/')}{RPC_PATH}",
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION,
            )
        ],
        capabilities=AgentCapabilities(
            streaming=False, push_notifications=False, extended_agent_card=False
        ),
        security_schemes={_BEARER: scheme},
        security_requirements=[requirement],
        default_input_modes=[REQUEST_MEDIA_TYPE],
        default_output_modes=[REPORT_MEDIA_TYPE],
        skills=[skill],
    )


def build_app(
    engineer: EngineerPort,
    cases: CaseLibrary,
    peers: PeerRegistry,
    settings: AgentSettings,
) -> Starlette:
    """The ASGI app. The task store scopes each task to its peer, so another peer's task
    ID reads as not found."""
    card = agent_card(settings.public_url)
    ledger = RequestLedger(settings.quota)
    executor = EngineerExecutor(engineer, cases, settings.limit, ledger, settings.runs_root)
    handler = EngineerRequestHandler(executor, InMemoryTaskStore(), card, ledger)
    routes = [*create_agent_card_routes(card), *create_jsonrpc_routes(handler, RPC_PATH)]
    guard = Middleware(PeerAuthMiddleware, registry=peers, rpc_path=RPC_PATH)
    return Starlette(routes=routes, middleware=[guard])
