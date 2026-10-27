"""OpenAI-compatible chat client with tool calls, for llama.cpp and hosted Meta endpoints.

Every transport, status and envelope fault becomes a typed ``ProviderError``; an HTTP 200
with a malformed body is never treated as a success.
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

import httpx

from earthlab.llm.providers import ProviderConfig
from earthlab.llm.types import (
    ChatResponse,
    ProviderError,
    ProviderErrorKind,
    ToolCall,
    Usage,
)


class ChatClient(Protocol):
    config: ProviderConfig

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
        tool_choice: str = "auto",
    ) -> ChatResponse: ...


def status_error(resp: httpx.Response) -> ProviderError:
    code = resp.status_code
    if code in (401, 403):
        return ProviderError(ProviderErrorKind.AUTH, f"HTTP {code}")
    if code == 429:
        retry = resp.headers.get("retry-after")
        after = float(retry) if retry and retry.replace(".", "", 1).isdigit() else None
        return ProviderError(ProviderErrorKind.RATE_LIMIT, "HTTP 429", retry_after=after)
    if code >= 500:
        return ProviderError(ProviderErrorKind.SERVER, f"HTTP {code}")
    return ProviderError(ProviderErrorKind.BAD_REQUEST, f"HTTP {code}: {resp.text[:200]}")


def _tool_calls(message: dict[str, Any]) -> tuple[ToolCall, ...]:
    calls: list[ToolCall] = []
    for index, raw in enumerate(message.get("tool_calls") or []):
        function = raw["function"]
        arguments = function.get("arguments") or "{}"
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments)  # some servers send an object, not a string
        calls.append(
            ToolCall(
                id=raw.get("id") or f"call_{index}", name=function["name"], arguments=arguments
            )
        )
    return tuple(calls)


class OpenAICompatClient:
    def __init__(self, config: ProviderConfig, *, transport: httpx.BaseTransport | None = None):
        self.config = config
        self._client = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=config.timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict[str, str]:
        key = self.config.api_key()
        return {"Authorization": f"Bearer {key}"} if key else {}

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
        tool_choice: str = "auto",
    ) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
            **self.config.extra_body,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        started = time.perf_counter()
        resp = self._post(payload)
        wall = time.perf_counter() - started
        return self._parse(resp, wall)

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            resp = self._client.post("/chat/completions", json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorKind.TIMEOUT, type(exc).__name__) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderErrorKind.TRANSPORT, type(exc).__name__) from exc
        if resp.status_code >= 400:
            raise status_error(resp)
        return resp

    def _parse(self, resp: httpx.Response, wall: float) -> ChatResponse:
        try:
            body = resp.json()
            choice = body["choices"][0]
            message = choice["message"]
            calls = _tool_calls(message)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(ProviderErrorKind.MALFORMED, "unexpected response body") from exc
        usage = body.get("usage") or {}
        return ChatResponse(
            provider=self.config.name,
            model=self.config.model,
            served_model=body.get("model"),
            request_id=body.get("id") or resp.headers.get("x-request-id"),
            content=message.get("content") or "",
            reasoning=message.get("reasoning_content") or message.get("reasoning"),
            tool_calls=calls,
            finish_reason=choice.get("finish_reason"),
            usage=Usage(
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            ),
            wall_seconds=wall,
        )


def build_client(config: ProviderConfig) -> ChatClient:
    """Factory: callers never name a concrete client class."""
    if not config.enabled:
        raise RuntimeError(f"provider {config.name} is disabled in config")
    return OpenAICompatClient(config)
