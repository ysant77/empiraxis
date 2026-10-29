"""What the model servers report about themselves at the start of a bench run: model file,
server build, context size and sampling defaults. The request side (temperature, output
token limit) comes from the code. A probe failure is recorded, never guessed around.
"""

from __future__ import annotations

from typing import Any

import httpx

from earthlab.agent.loop import PLANNER_TEMPERATURE
from earthlab.llm.providers import ProviderConfig
from earthlab.llm.raw import GUARD_TEMPERATURE
from earthlab.safety.llama_guard import LlamaGuard

PROBE_SECONDS = 5.0
SAMPLING_KEYS = ("temperature", "top_p", "top_k", "min_p", "seed")


def _get(url: str, transport: httpx.BaseTransport | None) -> Any:
    with httpx.Client(timeout=PROBE_SECONDS, transport=transport) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


def _llamacpp(config: ProviderConfig, transport: httpx.BaseTransport | None) -> dict[str, Any]:
    root = config.base_url.rstrip("/").removesuffix("/v1")
    props = _get(f"{root}/props", transport)
    settings = props.get("default_generation_settings", {})
    params = settings.get("params", {})
    return {
        "server": "llama.cpp",
        "model_path": props.get("model_path"),
        "model_alias": props.get("model_alias"),
        "build_info": props.get("build_info"),
        "n_ctx": settings.get("n_ctx"),
        "sampling_defaults": {key: params.get(key) for key in SAMPLING_KEYS},
    }


def _ollama(config: ProviderConfig, transport: httpx.BaseTransport | None) -> dict[str, Any]:
    tags = _get(f"{config.base_url.rstrip('/')}/api/tags", transport)
    wanted = {config.model, f"{config.model}:latest"}
    digests = [m.get("digest") for m in tags.get("models", []) if m.get("name") in wanted]
    return {"server": "ollama", "model_digest": digests[0] if digests else None}


def server_settings(
    config: ProviderConfig, transport: httpx.BaseTransport | None = None
) -> dict[str, Any]:
    """Settings of a local or LAN server; a hosted endpoint records only its config."""
    if config.kind == "hosted":
        return {"server": "hosted", "note": "server settings are not visible to the client"}
    try:
        if config.api == "ollama_raw":
            return _ollama(config, transport)
        return _llamacpp(config, transport)
    except (httpx.HTTPError, ValueError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def planner_record(
    config: ProviderConfig, max_output_tokens: int, transport: httpx.BaseTransport | None = None
) -> dict[str, Any]:
    return {
        "provider": config.name,
        "model": config.model,
        "logical_model": config.logical_model,
        "request": {
            "temperature": PLANNER_TEMPERATURE,
            "max_tokens": max_output_tokens,
            "extra_body": config.extra_body,
        },
        "server": server_settings(config, transport),
    }


def guard_record(
    guard: LlamaGuard | None, transport: httpx.BaseTransport | None = None
) -> dict[str, Any]:
    """The safety model in use, or a plain statement that only the rule checks ran."""
    if guard is None:
        return {"enabled": False, "note": "rule checks only; no safety model"}
    config = guard.config
    record: dict[str, Any] = {"enabled": True, "name": guard.name}
    if config is not None:
        record |= {
            "provider": config.name,
            "model": config.model,
            "request": {"temperature": GUARD_TEMPERATURE},
            "server": server_settings(config, transport),
        }
    return record


def probe_failures(planner: dict[str, Any] | None, guard: dict[str, Any]) -> list[str]:
    """Names of the servers whose settings could not be read."""
    failed = []
    if planner is not None and "error" in planner["server"]:
        failed.append(planner["provider"])
    if "error" in guard.get("server", {}):
        failed.append(guard["provider"])
    return failed
