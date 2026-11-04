"""Qwen3 4B preflight for the ML Specialist seat (protocol m41-v1, section 6).

Conditions: identity; the M4 tool loop with an optional closing call; the same loop with a
forced closing call; and schema-constrained ModelAssessmentV1. Every attempt is counted.

Usage: python scripts/m41_qwen_preflight.py --models-dir DIR --out FILE
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

from earthlab.assess.contracts import EvidencePackageV1, ModelAssessmentV1
from earthlab.assess.llm import HttpStructuredClient, Sampling
from earthlab.assess.roles import ask, messages_for, package_text
from earthlab.assess.serving import SideServer
from earthlab.harness.identity import file_sha256, load_registry
from earthlab.llm.providers import load_providers

PROVIDER = "local-qwen3-4b-2507"
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "inspect_package",
            "description": "Return the evidence package.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_note",
            "description": "Submit the ML assessment note. This ends the task.",
            "parameters": {
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "required": ["note"],
            },
        },
    },
]
SYSTEM = (
    "You are the ML Specialist. First call inspect_package. Then assess the baseline and "
    "the candidates, and finish by calling submit_note with a short note."
)


def _post(base: str, body: dict[str, Any]) -> dict[str, Any]:
    resp = httpx.post(f"{base}/chat/completions", json=body, timeout=300)
    resp.raise_for_status()
    message: dict[str, Any] = resp.json()["choices"][0]["message"]
    return message


def tool_loop(base: str, pkg: EvidencePackageV1, closing: str) -> dict[str, Any]:
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": pkg.question},
    ]
    body = {
        "model": PROVIDER,
        "messages": msgs,
        "tools": TOOLS,
        "temperature": 0.0,
        "seed": 20261104,
        "max_tokens": 600,
        "tool_choice": "auto",
    }
    first = _post(base, body)
    calls = first.get("tool_calls") or []
    if not calls or calls[0]["function"]["name"] != "inspect_package":
        return {"ok": False, "stage": "first call", "text": (first.get("content") or "")[:200]}
    msgs += [
        first,
        {"role": "tool", "tool_call_id": calls[0].get("id", "c0"), "content": package_text(pkg)},
    ]
    second = _post(base, {**body, "messages": msgs, "tool_choice": closing})
    names = [c["function"]["name"] for c in second.get("tool_calls") or []]
    ok = "submit_note" in names
    return {
        "ok": ok,
        "stage": "closing call",
        "tool_calls": names,
        "text": (second.get("content") or "")[:200],
    }


def schema_runs(client: HttpStructuredClient, pkgs: list[EvidencePackageV1]) -> list[dict]:
    rows = []
    for seed in (20261104, 7):
        for pkg in pkgs:
            log: list[dict[str, Any]] = []
            out = ask(
                "ml_engineer",
                client,
                messages_for("ml_engineer", pkg, {}),
                Sampling(seed=seed, max_tokens=2000),
                lambda e, d: log.append(d),
            )
            rows.append(
                {
                    "package": pkg.package_id,
                    "seed": seed,
                    "valid": isinstance(out, ModelAssessmentV1),
                    "attempts": len(log),
                    "faults": [x["fault"] for x in log if x["fault"]],
                    "findings": len(out.findings) if isinstance(out, ModelAssessmentV1) else 0,
                }
            )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    registry = load_registry(Path("config/benchmark/checkpoints.yaml"))
    path = next(a.models_dir.rglob(registry[PROVIDER].file))
    digest = file_sha256(path)
    pkgs = [
        EvidencePackageV1.model_validate_json(p.read_text())
        for p in sorted(Path("examples/assess/packages").glob("*.json"))
    ]
    side = SideServer({PROVIDER: path}, registry, port=8081)
    try:
        load = side.ensure(PROVIDER)
        cfg = load_providers(Path("config/providers.yaml"))[PROVIDER]
        client = HttpStructuredClient(cfg.model_copy(update={"base_url": side.base_url}))
        report = {
            "identity": {
                "file": path.name,
                "sha256": digest,
                "matches_registry": digest == registry[PROVIDER].sha256,
                "load_seconds": load,
            },
            "tool_auto": [tool_loop(side.base_url, p, "auto") for p in pkgs],
            "tool_required": [tool_loop(side.base_url, p, "required") for p in pkgs],
            "schema": schema_runs(client, pkgs),
        }
    finally:
        side.stop()
    report["summary"] = {
        k: f"{sum(r['ok'] for r in report[k])}/{len(report[k])}"
        for k in ("tool_auto", "tool_required")
    }
    report["summary"]["schema"] = f"{sum(r['valid'] for r in report['schema'])}/8"
    a.out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
