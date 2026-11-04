"""Run M4.1 council arms on frozen evidence packages. Local servers only.

Usage:
  python scripts/m41_run.py --arms S,H --packages a,b --out DIR --models-dir DIR [--critic P]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from earthlab.assess.contracts import EvidencePackageV1
from earthlab.assess.council import Council, arm_of, load_spec
from earthlab.assess.llm import HttpStructuredClient, StructuredClient
from earthlab.assess.pipeline import execute
from earthlab.assess.serving import SideServer, verify_identity
from earthlab.harness.identity import load_registry
from earthlab.llm.providers import load_providers
from earthlab.trace import RunTrace

PACKAGES = Path("examples/assess/packages")


def package(prefix: str) -> EvidencePackageV1:
    path = next(PACKAGES.glob(f"{prefix}-*.json"))
    return EvidencePackageV1.model_validate_json(path.read_text())


def models_map(root: Path, files: dict[str, str]) -> dict[str, Path]:
    found = {p.name: p for p in root.rglob("*.gguf")}
    return {prov: found[name] for prov, name in files.items() if name in found}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", required=True)
    ap.add_argument("--packages", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--models-dir", type=Path, required=True)
    ap.add_argument("--critic", default=None)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--temperature", type=float, default=None)
    a = ap.parse_args()
    spec = load_spec(Path("config/assess/council.yaml"))
    if a.temperature is not None:
        spec = spec.model_copy(
            update={"sampling": spec.sampling.model_copy(update={"temperature": a.temperature})}
        )
    providers = load_providers(Path("config/providers.yaml"))
    registry = load_registry(Path("config/benchmark/checkpoints.yaml"))
    side = SideServer(
        models_map(a.models_dir, {p: c.file for p, c in registry.items()}), registry, port=8081
    )
    clients: dict[str, StructuredClient] = {}
    for name in sorted(providers):
        if name in registry:
            cfg = providers[name]
            if name not in spec.main_providers:
                cfg = cfg.model_copy(update={"base_url": side.base_url})
            clients[name] = HttpStructuredClient(cfg)
    verify_identity(providers["local-glimmer"].base_url, registry["local-glimmer"])
    try:
        for rep in range(a.repeat):
            for arm_name in a.arms.split(","):
                over = {"critic": a.critic} if a.critic and arm_name == "HC" else {}
                arm = arm_of(spec, arm_name, **over)
                for prefix in a.packages.split(","):
                    pkg = package(prefix)
                    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                    folder = a.out / f"{stamp}-{arm_name}-{pkg.package_id}-r{rep + 1}"
                    trace = RunTrace(folder / "trace.jsonl")
                    out = execute(pkg, Council(spec, arm, clients, registry, side), trace)
                    out["temperature"] = spec.sampling.temperature
                    (folder / "result.json").write_text(json.dumps(out, indent=1) + "\n")
                    print(
                        folder.name,
                        out["status"],
                        out.get("decision"),
                        out.get("agrees_with_code_rule"),
                        out["wall_seconds"],
                        flush=True,
                    )
    finally:
        side.stop()


if __name__ == "__main__":
    main()
