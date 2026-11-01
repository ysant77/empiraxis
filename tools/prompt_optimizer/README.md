# Prompt optimizer (offline developer tool)

This folder is not part of the product. Nothing in `src/` imports it. `pyproject.toml` does not list DSPy.

Tool: DSPy 3.4.1 (MIT) with MIPROv2. GEPA 0.1.4 (MIT) is in the lock for a later trial.
`requirements.lock` pins every package with hashes.

Environment: outside the repo, at `~/Documents/meta-ai/prompt-optimizer-env`. Rebuild it with:

```bash
uv venv --python 3.12 ~/Documents/meta-ai/prompt-optimizer-env
uv pip install --python ~/Documents/meta-ai/prompt-optimizer-env/bin/python --require-hashes -r tools/prompt_optimizer/requirements.lock
```

Check with no model:

```bash
~/Documents/meta-ai/prompt-optimizer-env/bin/python -I tools/prompt_optimizer/optimize.py --dry-run
```

Run (Phase 2 only, with a Qwen3 4B server on port 8081):

```bash
~/Documents/meta-ai/prompt-optimizer-env/bin/python -I tools/prompt_optimizer/optimize.py --out candidate.json
```

The output is a candidate text with held-out scores. A person reviews it. Nothing is applied
automatically. See `docs/benchmark-matrix-protocol.md`, section 7.
