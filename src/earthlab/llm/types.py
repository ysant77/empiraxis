"""Typed chat responses shared by every model provider."""

from __future__ import annotations

from enum import StrEnum

from earthlab.contracts import Strict


class ToolCall(Strict):
    id: str
    name: str
    arguments: str


class Usage(Strict):
    """Token counts as the provider reports them. None means not reported, not zero."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ChatResponse(Strict):
    provider: str
    model: str
    served_model: str | None
    request_id: str | None
    content: str
    reasoning: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str | None
    usage: Usage
    wall_seconds: float


class ProviderErrorKind(StrEnum):
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    BAD_REQUEST = "bad_request"
    MALFORMED = "malformed"


RETRYABLE = frozenset(
    {
        ProviderErrorKind.RATE_LIMIT,
        ProviderErrorKind.SERVER,
        ProviderErrorKind.TIMEOUT,
        ProviderErrorKind.TRANSPORT,
    }
)


class ProviderError(RuntimeError):
    def __init__(self, kind: ProviderErrorKind, message: str, retry_after: float | None = None):
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE
