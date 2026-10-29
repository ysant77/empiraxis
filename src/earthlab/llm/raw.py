"""Raw-prompt completion for models whose prompt format must not be re-templated.

Llama Guard reads a custom policy only when the prompt reaches it unchanged. Ollama's
``/api/generate`` with ``raw: true`` and llama.cpp's ``/completion`` both do that; the
OpenAI-style ``/v1/completions`` route applies the server's own template and does not.
"""

from __future__ import annotations

from typing import Any

import httpx

from earthlab.llm.client import status_error
from earthlab.llm.providers import ProviderConfig
from earthlab.llm.types import ProviderError, ProviderErrorKind

GUARD_TEMPERATURE = 0


class RawCompletionClient:
    def __init__(self, config: ProviderConfig, *, transport: httpx.BaseTransport | None = None):
        if config.api == "openai_chat":
            raise ValueError(f"{config.name}: raw completion needs api ollama_raw or llamacpp_raw")
        self.config = config
        self._client = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=config.timeout_seconds,
            transport=transport,
        )

    def _request(self, prompt: str, max_tokens: int) -> tuple[str, dict[str, Any]]:
        if self.config.api == "ollama_raw":
            return "/api/generate", {
                "model": self.config.model,
                "prompt": prompt,
                "raw": True,
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": GUARD_TEMPERATURE},
            }
        return "/completion", {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": GUARD_TEMPERATURE,
        }

    def complete(self, prompt: str, max_tokens: int) -> str:
        path, payload = self._request(prompt, max_tokens)
        try:
            resp = self._client.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorKind.TIMEOUT, type(exc).__name__) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderErrorKind.TRANSPORT, type(exc).__name__) from exc
        if resp.status_code >= 400:
            raise status_error(resp)
        try:
            body = resp.json()
            text = body["response"] if self.config.api == "ollama_raw" else body["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(ProviderErrorKind.MALFORMED, "unexpected response body") from exc
        if not isinstance(text, str):
            raise ProviderError(ProviderErrorKind.MALFORMED, "completion text is not a string")
        return text
