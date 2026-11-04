"""Run the M4.1 critic test for the rule critic and for model critics. Local servers only.

Usage: python scripts/m41_critic_bench.py --critics rules,local-glimmer --out DIR --models-dir DIR
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from earthlab.assess.contracts import (
    CRITIC_CONTRACTS,
    Critique,
    CritiqueV1,
    CritiqueV2,
    EvidencePackageV1,
)
from earthlab.assess.council import load_spec
from earthlab.assess.critic_bench import (
    CaseV1,
    load_cases,
    load_seeded,
    rule_critique,
    run_bench,
)
from earthlab.assess.llm import HttpStructuredClient
from earthlab.assess.roles import ask, messages_for
from earthlab.assess.serving import SideServer, verify_identity, verify_served
from earthlab.harness.identity import load_registry
from earthlab.llm.providers import load_providers
from earthlab.trace import RunTrace

PACKAGES = Path("examples/assess/packages")


def packages() -> dict[str, EvidencePackageV1]:
    found = {}
    for path in sorted(PACKAGES.glob("*.json")):
        pkg = EvidencePackageV1.model_validate_json(path.read_text())
        found.setdefault(pkg.package_id[0], pkg)  # cases use packages A to D only
    return found


def model_critic(provider: str, a: argparse.Namespace, trace: RunTrace) -> Any:
    spec = load_spec(Path("config/assess/council-m41-v2.yaml"))
    registry = load_registry(Path("config/benchmark/checkpoints.yaml"))
    cfg = load_providers(Path("config/providers.yaml"))[provider]
    side = None
    if provider not in spec.main_providers:
        files = {p.name: p for p in a.models_dir.rglob("*.gguf")}
        side = SideServer({provider: files[registry[provider].file]}, registry, port=8081)
        load = side.ensure(provider)
        trace.append(
            "model_switch",
            "runtime",
            to=provider,
            load_seconds=load,
            checkpoint_verified=side.digests[provider],
        )
        cfg = cfg.model_copy(update={"base_url": side.base_url})
    else:
        trace.append(
            "checkpoint_verified", "runtime", **verify_served(cfg.base_url, registry[provider])
        )
    verify_identity(cfg.base_url, registry[provider])
    client = HttpStructuredClient(cfg)
    sampling = spec.sampling.model_copy(
        update={"template_kwargs": spec.template_kwargs.get(provider, {})}
    )

    contract = CRITIC_CONTRACTS[a.contract]

    def critic(case: CaseV1, pkg: EvidencePackageV1) -> Critique | None:
        def record(event: str, data: dict[str, Any]) -> None:
            trace.append(event, "critic", case=case.id, **data)

        msgs = messages_for("critic", pkg, {"lead_plan": case.plan.model_dump(mode="json")})
        out = ask("critic", client, msgs, sampling, record, contract)
        if isinstance(out, CritiqueV1 | CritiqueV2):
            trace.append("role_output", "critic", case=case.id, output=out.model_dump(mode="json"))
            return out
        return None

    return critic, side


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--critics", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--models-dir", type=Path, required=True)
    ap.add_argument("--contract", choices=["v1", "v2"], default="v1")
    a = ap.parse_args()
    cases = load_cases(Path("examples/assess/critic-cases.json"))
    seeded = load_seeded(Path("examples/assess/critic-case-evidence.json"))
    pkgs = packages()
    a.out.mkdir(parents=True, exist_ok=True)
    for name in a.critics.split(","):
        tag = name if a.contract == "v1" or name == "rules" else f"{name}-{a.contract}"
        trace = RunTrace(a.out / f"critic-{tag}.trace.jsonl")
        side = None
        if name == "rules":
            critic: Any = lambda case, pkg: rule_critique(case.plan, pkg)  # noqa: E731
        else:
            critic, side = model_critic(name, a, trace)
        try:
            scores, totals = run_bench(cases, pkgs, critic, seeded)
        finally:
            if side is not None:
                side.stop()
        body = {
            "critic": tag,
            "summary": totals,
            "cases": [s.model_dump(mode="json") for s in scores],
        }
        (a.out / f"critic-{tag}.json").write_text(json.dumps(body, indent=1) + "\n")
        print(tag, json.dumps(totals), flush=True)


if __name__ == "__main__":
    main()
