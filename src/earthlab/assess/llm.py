"""Structured model calls: one JSON object per call, constrained by the contract's schema.

llama.cpp turns `response_format.json_schema` into a grammar, so the reply is valid JSON of
the requested shape. The contract still parses it, because a grammar does not check value
limits or cross-field rules. Temperature and seed are explicit on every call.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

import httpx
from pydantic import Field

from earthlab.contracts import Strict
from earthlab.llm.client import status_error
from earthlab.llm.providers import ProviderConfig
from earthlab.llm.types import ProviderError, ProviderErrorKind


class Sampling(Strict):
    temperature: float = 0.0
    seed: int = 20261104
    max_tokens: int = 1400
    template_kwargs: dict[str, Any] = Field(default_factory=dict)


class Reply(Strict):
    content: str
    reasoning_chars: int
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    wall_seconds: float
    served_model: str | None
    request_id: str | None


class StructuredClient(Protocol):
    config: ProviderConfig

    def complete(
        self, messages: list[dict[str, str]], schema: dict[str, Any], sampling: Sampling
    ) -> Reply: ...


def payload(
    model: str, messages: list[dict[str, str]], schema: dict[str, Any], sampling: Sampling
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": sampling.max_tokens,
        "temperature": sampling.temperature,
        "seed": sampling.seed,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "record", "schema": schema, "strict": True},
        },
    }
    if sampling.template_kwargs:
        body["chat_template_kwargs"] = dict(sampling.template_kwargs)
    return body


def parse_reply(body: dict[str, Any], wall: float) -> Reply:
    try:
        choice = body["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(ProviderErrorKind.MALFORMED, "unexpected response body") from exc
    usage = body.get("usage") or {}
    return Reply(
        content=message.get("content") or "",
        reasoning_chars=len(message.get("reasoning_content") or ""),
        finish_reason=choice.get("finish_reason"),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        wall_seconds=round(wall, 3),
        served_model=body.get("model"),
        request_id=body.get("id"),
    )


class HttpStructuredClient:
    """OpenAI-compatible endpoint. Local and LAN hosts only, by the provider config rule."""

    def __init__(self, config: ProviderConfig, *, transport: httpx.BaseTransport | None = None):
        self.config = config
        self._http = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=config.timeout_seconds,
            transport=transport,
        )

    def complete(
        self, messages: list[dict[str, str]], schema: dict[str, Any], sampling: Sampling
    ) -> Reply:
        body = payload(self.config.model, messages, schema, sampling)
        started = time.perf_counter()
        try:
            resp = self._http.post("/chat/completions", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorKind.TIMEOUT, type(exc).__name__) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderErrorKind.TRANSPORT, type(exc).__name__) from exc
        if resp.status_code >= 400:
            raise status_error(resp)
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(ProviderErrorKind.MALFORMED, "body is not JSON") from exc
        return parse_reply(data, time.perf_counter() - started)
