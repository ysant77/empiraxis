"""Preflight of one model server for a council seat, then the seeded-fault critic test.

It never starts or stops a server. It checks that the running llama-server loaded the file
that the checkpoint registry names (the `/props` model path), optionally recomputes the file
digest, and runs the ten labelled critic cases against the provider. Results go to --out.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from earthlab.harness import critic_eval
from earthlab.harness.identity import file_sha256, load_registry
from earthlab.llm.client import build_client
from earthlab.llm.providers import load_providers

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "examples" / "replay" / "scenario-muse-method-comparison" / "evaluation-plan-1.json"


def served_file(base_url: str) -> dict[str, str]:
    props = httpx.get(base_url.removesuffix("/v1") + "/props", timeout=10).json()
    return {"model_path": str(props.get("model_path")), "build": str(props.get("build_info"))}


def main() -> int:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("--provider", required=True)
    top.add_argument("--out", type=Path, required=True)
    top.add_argument("--gguf", type=Path, help="recompute this file's SHA-256 and compare")
    top.add_argument("--skip-cases", action="store_true")
    args = top.parse_args()
    providers = load_providers(ROOT / "config" / "providers.yaml")
    registry = load_registry(ROOT / "config" / "benchmark" / "checkpoints.yaml")
    cfg, ckpt = providers[args.provider], registry[args.provider]
    args.out.mkdir(parents=True, exist_ok=True)
    info = served_file(cfg.base_url)
    result: dict[str, object] = {
        "provider": args.provider, "registry_file": ckpt.file, "registry_sha256": ckpt.sha256,
        "server": info, "server_file_matches": Path(info["model_path"]).name == ckpt.file,
    }  # fmt: skip
    if args.gguf is not None:
        digest = file_sha256(args.gguf)
        result |= {"file_sha256": digest, "file_sha256_matches": digest == ckpt.sha256}
    if not args.skip_cases:
        rows = critic_eval.evaluate(
            build_client(cfg.model_copy(update={"enabled": True})),
            critic_eval.load_report(REPORT), args.out / f"critic-{args.provider}",
        )  # fmt: skip
        result["critic_eval"] = critic_eval.write(
            args.out / f"critic-{args.provider}.json", cfg.model, rows
        )
    (args.out / f"preflight-{args.provider}.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "critic_eval"}, indent=2))
    if "critic_eval" in result:
        print(json.dumps(result["critic_eval"]["summary"], indent=2))  # type: ignore[index]
    return 0 if result["server_file_matches"] else 1


if __name__ == "__main__":
    sys.exit(main())
