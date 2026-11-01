# Model registry

Evidence for each model, as of 2026-11-01. `config/roles/bindings.yaml` controls which model
can serve a role. This file records what was measured. "Not measured" means that no run
produced the value.

Muse Glimmer is the only model that does scientific work. Do not substitute another model in
a Muse arm. A disabled candidate cannot serve a role.

## Models in use

| Field | Muse Glimmer 30B | Guard |
|---|---|---|
| Role | Orchestrator, PM, geospatial engineer | Input and answer safety checks |
| Served identity | `muse-glimmer-30B` | `earthlab-guard` (reported as `llama-guard-3-8b`) |
| Backend | llama-server, build `b11669-620d2225c`, port 8080 | Ollama, port 11434 |
| Revision | Weights SHA-256 `4cc57c0f51040a22...` | Digest `ddc07af15606...` |
| Quantization | Q4_K_M KQuant, 16.76 GB, with DFlash drafter | Q4_K_M, 4.9 GB |
| Context | 32,768 tokens | Not measured |
| Licence | Apache-2.0 as recorded. No licence file is beside the weights: check the model card before release | Llama community licence: check before release |
| Tools | Tool calls and JSON schema pass | Not applicable |
| Cost | No provider charge. Energy is not measured | No provider charge. Energy is not measured |
| Speed | About 4 to 5 completion tokens per second | Not measured separately |
| Memory | System wired peak 26.5 GB and swap peak 19.3 GB, with other programs open. Process RSS does not show model memory | Included in the system figures |
| Reliability | 17 of 17 live runs gave a correct status or a safe stop. See below | Guard was on in all 17 runs |

## Live evidence

Twelve runs at `5b91554` and five reruns at `a664698`. One run per cell in the twelve-run
matrix, in rotated order. These numbers describe these runs only. They do not show that one
topology is better than another.

- Verified values were correct in every arm: 77,426 ha with valid fraction 0.970144 for
  September 2015, and the NEA peak for west at 471 ug/m3 over 1,464 hours.
- October 2015 abstained in every arm, because the valid fraction 0.4597 is below the 0.8 gate.
- The causal question abstained in 3 of 3 reruns on the separate topology. One earlier run
  stopped at `out_of_scope`. That run made no false claim, and `a664698` changed the routing.
- Median wall time in the matrix: direct 236 s, separate 678 s, combined 731 s.

## Installed but not evaluated

These models have no role and no preflight. Each needs a preflight before use. Each is for
proposal-only engineering work and never does scientific work.

| Model | Digest | Size | Quantization |
|---|---|---|---|
| `qwen3.8:27b` | `47951e4a6661` | 18 GB | nvfp4 |
| `gemma4:26b` | `48eb98ec778c` | 16 GB | nvfp4 |
| `gpt-oss:20b` | `f38aa0c53da5` | 13 GB | MXFP4 |
| `gemma3:4b` | `68ceab7e468a` | 3.4 GB | Q4_K_M |
| `qwen3:4b` | `359d7dd4bcda` | 2.5 GB | Q4_K_M |

The 16 GB and 18 GB models do not fit in memory while Muse Glimmer is loaded.

## Not available

- Llama 3.2 3B is not installed, so the Llama PM with Muse engineer arm has not run.
- Muse Spark Open on Baseten: no probe was made. No hosted model was called.
