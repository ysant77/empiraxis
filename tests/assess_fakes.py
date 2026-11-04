"""Scripted structured clients and a fake side server for M4.1 council tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from earthlab.assess.contracts import EvidencePackageV1
from earthlab.assess.llm import Reply, Sampling
from earthlab.harness.identity import CheckpointV1
from earthlab.llm.providers import ProviderConfig
from earthlab.llm.types import ProviderError

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "examples" / "assess" / "packages"
SHA = "a" * 64


def package(prefix: str) -> EvidencePackageV1:
    path = next(PACKAGES.glob(f"{prefix}-*.json"))
    return EvidencePackageV1.model_validate_json(path.read_text())


def config(name: str) -> ProviderConfig:
    return ProviderConfig(
        name=name, kind="local", base_url="http://127.0.0.1:9/v1", model=name, logical_model=name
    )


def checkpoint(provider: str, sha: str = SHA) -> CheckpointV1:
    return CheckpointV1(
        provider=provider,
        family="test",
        file=f"{provider}.gguf",
        sha256=sha,
        size_bytes=1,
        quantization="Q4",
        licence="test",
        source="test",
    )


class ScriptedClient:
    """Returns the next scripted reply. A dict is sent as JSON; an exception is raised."""

    def __init__(self, name: str, replies: list[Any]):
        self.config = config(name)
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, messages: list[dict[str, str]], schema: dict[str, Any], sampling: Sampling
    ) -> Reply:
        self.calls.append({"messages": messages, "schema": schema, "sampling": sampling})
        item = self.replies.pop(0)
        if isinstance(item, ProviderError):
            raise item
        content = item if isinstance(item, str) else json.dumps(item)
        return Reply(
            content=content,
            reasoning_chars=0,
            finish_reason="stop",
            prompt_tokens=10,
            completion_tokens=5,
            wall_seconds=0.1,
            served_model=self.config.model,
            request_id="r",
        )


class FakeSide:
    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.current: str | None = None

    def ensure(self, provider: str) -> float:
        if provider == self.current:
            return 0.0
        self.loaded.append(provider)
        self.current = provider
        return 1.5

    def stop(self) -> float:
        self.current = None
        return 0.0


def finding(fid: str, fault: str, evidence: list[str], **kw: Any) -> dict[str, Any]:
    return {
        "id": fid,
        "fault_class": fault,
        "claim": kw.pop("claim", "A backed concern here."),
        "evidence": evidence,
        "cited_values": kw.pop("cited", {}),
        "severity": kw.pop("severity", "medium"),
        "action": kw.pop("action", "add_check"),
        "uncertainty": "small sample",
    }


def lead_plan(decision: str = "retain_baseline", **kw: Any) -> dict[str, Any]:
    return {
        "dispositions": kw.pop("dispositions", []),
        "decision": decision,
        "inputs_used": kw.pop("inputs_used", ["m3_eval"]),
        "excluded_inputs": kw.pop("excluded_inputs", []),
        "plan": kw.pop("plan", "Retain the lagged ridge and state the elevated-hour limit."),
        "claims": kw.pop("claims", []),
        "unresolved": [],
        "limitations": [],
    }
