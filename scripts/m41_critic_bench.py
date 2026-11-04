"""Run the M4.1 critic test for the rule critic and for model critics. Local servers only.

Usage: python scripts/m41_critic_bench.py --critics rules,local-glimmer --out DIR --models-dir DIR
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from earthlab.assess.contracts import CritiqueV1, EvidencePackageV1
from earthlab.assess.council import load_spec
from earthlab.assess.critic_bench import CaseV1, load_cases, rule_critique, run_bench
from earthlab.assess.llm import HttpStructuredClient
from earthlab.assess.roles import ask, messages_for
from earthlab.assess.serving import SideServer, verify_identity
from earthlab.harness.identity import load_registry
from earthlab.llm.providers import load_providers
from earthlab.trace import RunTrace

PACKAGES = Path("examples/assess/packages")


def packages() -> dict[str, EvidencePackageV1]:
    found = {}
    for path in sorted(PACKAGES.glob("*.json")):
        pkg = EvidencePackageV1.model_validate_json(path.read_text())
        found[pkg.package_id[0]] = pkg
    return found


def model_critic(provider: str, a: argparse.Namespace, trace: RunTrace) -> Any:
    spec = load_spec(Path("config/assess/council.yaml"))
    registry = load_registry(Path("config/benchmark/checkpoints.yaml"))
    cfg = load_providers(Path("config/providers.yaml"))[provider]
    side = None
    if provider not in spec.main_providers:
        files = {p.name: p for p in a.models_dir.rglob("*.gguf")}
        side = SideServer({provider: files[registry[provider].file]}, registry, port=8081)
        load = side.ensure(provider)
        trace.append("model_switch", "runtime", to=provider, load_seconds=load)
        cfg = cfg.model_copy(update={"base_url": side.base_url})
    verify_identity(cfg.base_url, registry[provider])
    client = HttpStructuredClient(cfg)
    sampling = spec.sampling.model_copy(
        update={"template_kwargs": spec.template_kwargs.get(provider, {})}
    )

    def critic(case: CaseV1, pkg: EvidencePackageV1) -> CritiqueV1 | None:
        def record(event: str, data: dict[str, Any]) -> None:
            trace.append(event, "critic", case=case.id, **data)

        msgs = messages_for("critic", pkg, {"lead_plan": case.plan.model_dump(mode="json")})
        out = ask("critic", client, msgs, sampling, record)
        if isinstance(out, CritiqueV1):
            trace.append("role_output", "critic", case=case.id, output=out.model_dump(mode="json"))
            return out
        return None

    return critic, side


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--critics", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--models-dir", type=Path, required=True)
    a = ap.parse_args()
    cases = load_cases(Path("examples/assess/critic-cases.json"))
    pkgs = packages()
    a.out.mkdir(parents=True, exist_ok=True)
    for name in a.critics.split(","):
        trace = RunTrace(a.out / f"critic-{name}.trace.jsonl")
        side = None
        if name == "rules":
            critic: Any = lambda case, pkg: rule_critique(case.plan, pkg)  # noqa: E731
        else:
            critic, side = model_critic(name, a, trace)
        try:
            scores, totals = run_bench(cases, pkgs, critic)
        finally:
            if side is not None:
                side.stop()
        body = {
            "critic": name,
            "summary": totals,
            "cases": [s.model_dump(mode="json") for s in scores],
        }
        (a.out / f"critic-{name}.json").write_text(json.dumps(body, indent=1) + "\n")
        print(name, json.dumps(totals), flush=True)


if __name__ == "__main__":
    main()
