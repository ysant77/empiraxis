"""Provider endpoint configuration, loaded from YAML. Secrets come from the environment."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlparse

import yaml
from pydantic import Field, model_validator

from earthlab.contracts import Strict

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_private_host(host: str) -> bool:
    if host in _LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


class ProviderConfig(Strict):
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    kind: Literal["local", "lan", "hosted"]
    api: Literal["openai_chat", "ollama_raw", "llamacpp_raw"] = "openai_chat"
    base_url: str
    model: str
    logical_model: str = Field(description="Meta model family, e.g. muse-glimmer-30b.")
    open_weight: bool = True
    api_key_env: str | None = None
    timeout_seconds: float = Field(default=600.0, gt=0)
    usd_per_mtok_input: float | None = Field(default=None, ge=0)
    usd_per_mtok_output: float | None = Field(default=None, ge=0)
    price_source: str | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def _transport_is_safe(self) -> Self:
        url = urlparse(self.base_url)
        if url.scheme == "https":
            return self
        if url.scheme == "http" and _is_private_host(url.hostname or ""):
            return self
        raise ValueError(f"{self.name}: plain HTTP is allowed only for local or LAN hosts")

    def api_key(self) -> str | None:
        """Read the key at call time; it is never stored on the config object."""
        if self.api_key_env is None:
            return None
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise RuntimeError(f"{self.name}: environment variable {self.api_key_env} is not set")
        return key

    def estimate_cost_usd(
        self, prompt_tokens: int | None, completion_tokens: int | None
    ) -> float | None:
        """Estimate from a dated price table. None when prices or usage are unknown."""
        if self.usd_per_mtok_input is None or self.usd_per_mtok_output is None:
            return None
        if prompt_tokens is None or completion_tokens is None:
            return None
        return (
            prompt_tokens * self.usd_per_mtok_input + completion_tokens * self.usd_per_mtok_output
        ) / 1_000_000


def load_providers(path: Path) -> dict[str, ProviderConfig]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    configs = [ProviderConfig.model_validate(item) for item in raw.get("providers", [])]
    return {c.name: c for c in configs}
