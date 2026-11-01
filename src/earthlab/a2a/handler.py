"""The SDK request handler, with typed parsing and idempotency in front of the task.

The protocol lets only the server choose a task ID, so idempotency keys on the typed
request's `request_id`. A first send claims the key and fixes the task's server IDs before
the SDK starts the task. A repeat returns that task as it stands now and starts nothing.
A malformed request or an exhausted quota gets a protocol error, and no task exists.
"""

from __future__ import annotations

from typing import cast

from a2a.helpers.proto_helpers import get_data_parts
from a2a.server.agent_execution import AgentExecutor, RequestContext, SimpleRequestContextBuilder
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.tasks import TaskStore
from a2a.types.a2a_pb2 import (
    AgentCard,
    Message,
    SendMessageRequest,
    Task,
    TaskState,
    TaskStatus,
)
from a2a.utils.errors import InvalidParamsError, InvalidRequestError
from pydantic import ValidationError

from earthlab.a2a.admission import request_digest
from earthlab.a2a.contracts import REQUEST_MEDIA_TYPE, EngineerTaskRequestV1
from earthlab.a2a.executor import REQUEST_KEY, TICKET_KEY
from earthlab.a2a.ledger import QuotaExhausted, RequestConflict, RequestLedger, Ticket


def parse_request(message: Message) -> EngineerTaskRequestV1:
    """The one typed request in the message, or InvalidParamsError.

    The error names the failed fields only, so it never echoes a peer's value.
    """
    if message.task_id:
        raise InvalidParamsError(message="a follow-up message to a task is not supported")
    if len(message.parts) != 1 or message.parts[0].media_type != REQUEST_MEDIA_TYPE:
        raise InvalidParamsError(message=f"send one data part of type {REQUEST_MEDIA_TYPE}")
    found = get_data_parts(message.parts)
    if len(found) != 1:
        raise InvalidParamsError(message=f"send one data part of type {REQUEST_MEDIA_TYPE}")
    try:
        return EngineerTaskRequestV1.model_validate(found[0])
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) or "request" for e in exc.errors()})
        raise InvalidParamsError(message=f"invalid fields: {', '.join(fields)}") from exc


class _TicketContextBuilder(SimpleRequestContextBuilder):
    """Give the SDK the task and context IDs that the ledger fixed for this request."""

    async def build(
        self,
        context: ServerCallContext,
        params: SendMessageRequest | None = None,
        task_id: str | None = None,
        context_id: str | None = None,
        task: Task | None = None,
    ) -> RequestContext:
        ticket: Ticket | None = context.state.get(TICKET_KEY)
        if ticket is not None:
            task_id, context_id = ticket.task_id, ticket.context_id
        return await super().build(context, params, task_id, context_id, task)


class EngineerRequestHandler(DefaultRequestHandlerV2):
    def __init__(
        self,
        executor: AgentExecutor,
        task_store: TaskStore,
        agent_card: AgentCard,
        ledger: RequestLedger,
    ):
        super().__init__(
            executor, task_store, agent_card, request_context_builder=_TicketContextBuilder()
        )
        self._tasks = task_store
        self._ledger = ledger

    def _claim(self, message: Message, context: ServerCallContext) -> tuple[Ticket, bool]:
        request = parse_request(message)
        owner = context.user.user_name
        digest = request_digest(request)
        try:
            ticket, new = self._ledger.claim(
                owner, request.request_id, digest, message.context_id or None
            )
        except RequestConflict as exc:
            raise InvalidParamsError(
                message="request_id was already used for a different request"
            ) from exc
        except QuotaExhausted as exc:
            raise InvalidRequestError(message=f"quota_exhausted: {exc}") from exc
        context.state[REQUEST_KEY] = request
        context.state[TICKET_KEY] = ticket
        return ticket, new

    async def _current(self, ticket: Ticket, context: ServerCallContext) -> Task:
        """The claimed task now; in the moment before its first save, a submitted record."""
        stored = await self._tasks.get(ticket.task_id, context)
        if stored is not None:
            return stored
        state = TaskStatus(state=TaskState.TASK_STATE_SUBMITTED)
        return Task(id=ticket.task_id, context_id=ticket.context_id, status=state)

    async def on_message_send(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> Message | Task:
        ticket, new = self._claim(params.message, context)
        if not new:
            return await self._current(ticket, context)
        return cast("Message | Task", await super().on_message_send(params, context))
