from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from earthlab.llm.client import OpenAICompatClient, build_client
from earthlab.llm.providers import ProviderConfig, load_providers
from earthlab.llm.types import ProviderError, ProviderErrorKind

CONFIG = ProviderConfig(
    name="test-hosted",
    kind="hosted",
    base_url="https://example.test/v1",
    model="meta-models/muse-spark-open",
    logical_model="muse-spark-open",
    api_key_env="EARTHLAB_TEST_KEY",
    usd_per_mtok_input=1.0,
    usd_per_mtok_output=4.0,
)


def client_for(
    handler: Callable[[httpx.Request], httpx.Response], monkeypatch: pytest.MonkeyPatch
) -> OpenAICompatClient:
    monkeypatch.setenv("EARTHLAB_TEST_KEY", "sk-test-secret")
    return OpenAICompatClient(CONFIG, transport=httpx.MockTransport(handler))


def ok_body(message: dict[str, object]) -> dict[str, object]:
    return {
        "id": "req-1",
        "model": "served-x",
        "choices": [{"message": message, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


def test_tool_calls_usage_and_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        message: dict[str, object] = {
            "content": None,
            "reasoning_content": "think",
            "tool_calls": [
                {"id": "c1", "function": {"name": "rank_regions", "arguments": '{"a":1}'}},
                {"function": {"name": "inspect_coverage", "arguments": {"b": 2}}},
            ],
        }
        return httpx.Response(200, json=ok_body(message))

    tools = [{"type": "function", "function": {"name": "rank_regions"}}]
    resp = client_for(handler, monkeypatch).chat(
        [{"role": "user", "content": "q"}], tools, max_tokens=50, temperature=1.0
    )
    assert seen["auth"] == "Bearer sk-test-secret"
    assert isinstance(seen["body"], dict) and seen["body"]["tool_choice"] == "auto"
    assert [c.name for c in resp.tool_calls] == ["rank_regions", "inspect_coverage"]
    assert resp.tool_calls[1].id == "call_1" and json.loads(resp.tool_calls[1].arguments) == {
        "b": 2
    }
    assert resp.reasoning == "think" and resp.content == ""
    assert resp.usage.prompt_tokens == 100 and resp.served_model == "served-x"
    assert CONFIG.estimate_cost_usd(1_000_000, 1_000_000) == 5.0
    assert CONFIG.estimate_cost_usd(None, 5) is None


@pytest.mark.parametrize(
    ("status", "kind", "retryable"),
    [
        (401, ProviderErrorKind.AUTH, False),
        (429, ProviderErrorKind.RATE_LIMIT, True),
        (503, ProviderErrorKind.SERVER, True),
        (400, ProviderErrorKind.BAD_REQUEST, False),
    ],
)
def test_status_codes_map_to_typed_errors(
    monkeypatch: pytest.MonkeyPatch, status: int, kind: ProviderErrorKind, retryable: bool
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"retry-after": "2"}, text="nope")

    with pytest.raises(ProviderError) as info:
        client_for(handler, monkeypatch).chat([], [], max_tokens=1, temperature=0)
    assert info.value.kind == kind and info.value.retryable is retryable
    if status == 429:
        assert info.value.retry_after == 2.0


def test_malformed_200_and_transport_faults(monkeypatch: pytest.MonkeyPatch) -> None:
    def malformed(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(ProviderError, match="malformed"):
        client_for(malformed, monkeypatch).chat([], [], max_tokens=1, temperature=0)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderError, match="timeout"):
        client_for(timeout, monkeypatch).chat([], [], max_tokens=1, temperature=0)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = client_for(refused, monkeypatch)
    with pytest.raises(ProviderError, match="transport"):
        client.chat([], [], max_tokens=1, temperature=0)
    client.close()


def test_missing_key_and_unsafe_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EARTHLAB_TEST_KEY", raising=False)
    with pytest.raises(RuntimeError, match="not set"):
        CONFIG.api_key()
    with pytest.raises(ValueError, match="plain HTTP"):
        ProviderConfig.model_validate(
            {**CONFIG.model_dump(), "base_url": "http://api.example.com/v1"}
        )
    lan = ProviderConfig.model_validate({**CONFIG.model_dump(), "base_url": "http://10.0.0.5:8080"})
    assert lan.base_url.startswith("http://10.")
    local = ProviderConfig.model_validate({**CONFIG.model_dump(), "base_url": "http://localhost:1"})
    assert local.api_key_env is not None


def test_shipped_config_loads_and_disabled_providers_refuse() -> None:
    providers = load_providers(Path(__file__).resolve().parents[1] / "config" / "providers.yaml")
    assert providers["local-glimmer"].enabled
    assert providers["baseten-spark-open"].model == "meta-models/muse-spark-open"
    assert providers["local-glimmer"].api_key() is None
    with pytest.raises(RuntimeError, match="disabled"):
        build_client(providers["baseten-spark-open"])
    assert build_client(providers["local-glimmer"]).config.name == "local-glimmer"
