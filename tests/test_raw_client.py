from __future__ import annotations

import json

import httpx
import pytest

from earthlab.llm.providers import ProviderConfig
from earthlab.llm.raw import RawCompletionClient
from earthlab.llm.types import ProviderError

BASE = {
    "name": "guard",
    "kind": "local",
    "base_url": "http://127.0.0.1:1",
    "model": "earthlab-guard",
    "logical_model": "llama-guard-3-8b",
}


def client(api: str, handler: object) -> RawCompletionClient:
    config = ProviderConfig.model_validate({**BASE, "api": api})
    return RawCompletionClient(config, transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_ollama_raw_sends_unmodified_prompt() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(path=request.url.path, body=json.loads(request.content))
        return httpx.Response(200, json={"response": "unsafe\nS2"})

    assert client("ollama_raw", handler).complete("PROMPT", 12) == "unsafe\nS2"
    body = seen["body"]
    assert seen["path"] == "/api/generate" and isinstance(body, dict)
    assert body["raw"] is True and body["prompt"] == "PROMPT"


def test_llamacpp_raw_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/completion"
        return httpx.Response(200, json={"content": "safe"})

    assert client("llamacpp_raw", handler).complete("P", 5) == "safe"


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (httpx.Response(503), "server"),
        (httpx.Response(200, json={"wrong": 1}), "malformed"),
        (httpx.Response(200, json={"response": 5}), "malformed"),
    ],
)
def test_raw_errors_are_typed(response: httpx.Response, kind: str) -> None:
    with pytest.raises(ProviderError, match=kind):
        client("ollama_raw", lambda _: response).complete("P", 5)


def test_transport_faults_and_wrong_api() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderError, match="transport"):
        client("ollama_raw", down).complete("P", 5)
    with pytest.raises(ProviderError, match="timeout"):
        client("ollama_raw", slow).complete("P", 5)
    with pytest.raises(ValueError, match="raw completion"):
        RawCompletionClient(ProviderConfig.model_validate(BASE))
