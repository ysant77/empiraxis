# ORIGINS

This file records where each part of the repository comes from. It separates work done in the hackathon build window from earlier work by the same author.

## Build window

- Event: Meta Global AI Developer Hackathon 2026, Indie track.
- Build period in the participant guide: 27 October – 4 November 2026 (ET).
- Repository initialised: 27 October 2026, after 00:00 ET (12:00 SGT). Git shows the real commit times. No history was rewritten.

## Pre-event work by the same author, reused with disclosure

The author owns a private project, Axiom Council (`ysant77/axiom-council`, first commit 25 October 2026). Small parts of it were copied or adapted into this repository. The table lists every such part.

| File in this repo | Source in Axiom Council | Change |
| --- | --- | --- |
| `scripts/check_size.py` | `scripts/check_size.py` | Copied unchanged. |
| `.githooks/commit-msg`, `.githooks/pre-push` | `.githooks/` | Copied unchanged. |
| `.github/workflows/ci.yml` | `.github/workflows/ci.yml` | Copied; package name changed. |
| `src/earthlab/audit.py` | `src/axiom_council/audit.py` | Adapted: run-scoped trace, no task store. |
| `src/earthlab/hashing.py` | `content_hash` in `src/axiom_council/contracts.py` | Adapted. |
| `src/earthlab/llm/client.py` | `src/axiom_council/providers/openai_compat.py` | Rewritten: bearer auth, tool calls, reasoning text, error classes. |

Pre-event planning documents (scope, rules analysis, diagrams) guided the design. They are not part of this repository.

An earlier private planning bundle contained a small NEA PM2.5 parser sketch. Its ideas (day/month/year parsing, Singapore time, duplicate removal) informed `src/earthlab/data/nea_pm25.py`. The parser in this repository is new. It also handles a malformed timestamp format in the real file that the sketch did not handle.

## New in the build window

Everything not listed above: the data loader and quality report, the scientific tools, the independent verifier, the agent loop, the Meta model integration, the Prometheus metrics, the report, the CLI, the UI and all tests. See the Git history for exact commits.

## Third-party components

| Item | Source | Licence / terms |
| --- | --- | --- |
| Muse Glimmer 30B (GGUF) | https://huggingface.co/meta-models/Muse-Glimmer-30B-GGUF | Apache 2.0 and Meta usage policy |
| Muse Spark Open (hosted, when credits arrive) | Baseten / Fireworks / Modal | Provider terms; Meta licence |
| NEA Historical 1-hr PM2.5 | https://data.gov.sg/datasets/d_6c0d5fc34838b12472475fdb73c0af29/view | Singapore Open Data Licence v1.0 |
| Python libraries | `uv.lock` | Each package licence |

## Not part of this repository

FireScope Lab code, Lion City Atmos code, edge or mobile code, and any employer or university material.
