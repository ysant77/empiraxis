# Submission pack

This file holds the project description, the evidence references, the commands that reproduce them and the release checklist. Each number here comes from a file in this repository.

## Project description

Axiom EarthLab is a human-supervised geospatial engineering system built on Meta's Muse Glimmer 30B, which runs locally. Muse works in four seats: product manager, Geospatial Lead, data specialist and ML specialist. It scopes a research question and chooses a method. Deterministic code does the work, independent code scores it, and a person makes the final decision. Every step is in a hash-chained trace.

The system can train a model, reuse one, reject one, abstain or ask for evidence. Four recorded scenarios on the 2015 Southeast Asian haze show these decisions:

- S1: a GRU beats persistence but fails above 55 µg/m³, so it is adopted with limits.
- S2: a frozen GRU encoder with a fitted head beats logistic regression but loses to a persistence alarm, so the baseline stays.
- S3: a wind and rain test on ERA5 hindsight data is inconclusive, so no fire source is named.
- S4: a pretrained satellite model cannot run on imagery that does not cover the study box, so the system asks a person for resources.

The negative results are the point. In a comparison of 48 saved runs, a Muse team reached the same decision as the deterministic pipeline, at higher cost. So EarthLab keeps the simpler path. An optional critic by the same model found no fault that code rules had not found, so it stays off.

Research prototype. It is not a forecast, a health warning or a source attribution. It was built with AI-assisted engineering; the README says so.

## Evidence references

| Claim | Evidence |
|---|---|
| Muse did the planning in the team run: 17 model calls, 4 tool calls | `examples/replay/scenario-muse-team-exceedance/trace.jsonl`, `scripts/demo_contributions.py` |
| S1 to S4 numbers | `examples/replay/scenario-*`, `docs/four-scenario-demo.md` |
| The team reached the same outcome as the deterministic pipeline, at higher cost | `docs/comparative-evidence-report.md` |
| The critic added no detection; the gate stays off | `docs/method-review-validation-results.md`, `docs/method-review-gate-v1.md` |
| Distillation is not adopted | `docs/distillation-results-v1.md` |
| Exact S1 checkpoint reuse has no fair score; Prithvi did not run | `docs/release-acceptance.md` |
| The 20-milestone register: 16 bounded, 3 partial, 1 future | `docs/release-acceptance.md` |
| The hosted entry is replay-only | `docs/hosted-replay.md`, `tests/test_hosted_replay.py` |

## Reproduce

These commands need no model, no key and no network after `uv sync`.

```bash
git clone https://github.com/ysant77/axiom-earthlab.git
```

```bash
cd axiom-earthlab
```

```bash
uv sync --all-extras
```

Check each published run against its manifest and hash chain. Each command exits 0. A changed or missing file exits 1.

```bash
for r in sb05-september sb05b-october live-september-verified live-october-abstained scenario-s1-regression scenario-s2-encoder-reuse scenario-s3-transport scenario-s4-resource-request scenario-muse-team-exceedance; do uv run earthlab --data-dir data/nea replay examples/replay/$r || echo "FAILED $r"; done
```

Print the credit table of the Muse team run:

```bash
uv run python scripts/demo_contributions.py examples/replay/scenario-muse-team-exceedance
```

Open the app:

```bash
uv run --extra ui streamlit run src/earthlab/ui/app.py --server.address 127.0.0.1
```

Run the checks that CI runs:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run python scripts/check_limits.py src tests scripts && uv run pytest
```

## Release checklist

| Item | State on 2026-11-03 | Owner action |
|---|---|---|
| Release commit | `9087ccb`. All 9 published runs replay with exit 0 on a clean clone. A changed `result.json` and a missing file each exit 1. | none |
| Licence | Draft PR #91 proposes Apache-2.0 for the original software. Data and models keep their own terms. | Confirm the licence and the right to grant it, then merge #91. |
| Repository visibility | Private | Make it public when the rules require it. |
| Hosted replay | Not published | Follow `docs/hosted-replay.md`, then share the URL for verification. |
| Prithvi Level A | Blocked: no signed approval | Optional. Approve the queued request in the local operator UI. |
| Video | Not recorded | Record from `docs/demo-three-minute.md`. |
| Deadline | The internal target is 4 November, 22:00 to 23:00 SGT. | Confirm the official deadline on the portal. |
