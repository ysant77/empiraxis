# Submission pack

This file holds the project description, the evidence references, the commands that reproduce them and the release checklist. Each number here comes from a file in this repository.

## Project description

Empiraxis is a human-supervised geospatial engineering system built on Meta's Muse Glimmer 30B, which runs locally. Muse works in four seats: product manager, Geospatial Lead, data specialist and ML specialist. It scopes a research question and chooses a method. Deterministic code does the work, independent code scores it, and a person makes the final decision. Every step is in a hash-chained trace.

The system can train a model, reuse one, reject one, abstain or ask for evidence. Four recorded scenarios on the 2015 Southeast Asian haze show these decisions:

- S1: a GRU beats persistence but fails above 55 µg/m³, so it is adopted with limits.
- S2: a frozen GRU encoder with a fitted head beats logistic regression but loses to a persistence alarm, so the baseline stays.
- S3: a wind and rain test on ERA5 hindsight data is inconclusive, so no fire source is named.
- S4: a pretrained satellite model cannot run on imagery that does not cover the study box, so the system asks a person for resources.

Three runs on 3 November add to these:

- Muse asked for a signed acquisition of three days from the official NEA API. 333 values matched the local file and 17 did not.
- In M3, Muse directed one run that trained a tuned ridge and a TCN on the same rows. Neither beat the lagged ridge, so the Lead kept it.
- Five T+6 h predictions were issued before their target hour and scored against later published values: MAE 7.2 µg/m³, n = 5.

The negative results are the point. In a comparison of 48 saved runs, a Muse team reached the same decision as the deterministic pipeline, at higher cost. So Empiraxis keeps the simpler path. An optional critic by the same model found no fault that code rules had not found, so it stays off.

Two later stages add to these:

- M4 put different Meta checkpoints in different seats: Muse Glimmer 30B for the PM and Lead, Llama 3.2 3B Instruct for the specialists and an advisory critic. The recorded run made 13 model calls on 2 checkpoints. Code reached the same outcome. M4.1 (PR #117, in review) critiques the frozen M5 evidence. Its benchmark results are not final yet.
- M5 tested fire, wind and rain data with deterministic CPU models and no Meta model. No addition gave a supported gain over PM2.5 history on the held-out 2019 season. FIRMS latency is nominal and assumed. M5-B has no result.

Research prototype. It is not a forecast, a health warning or a source attribution. It was built with AI-assisted engineering; the README says so.

## Evidence references

| Claim | Evidence |
|---|---|
| Muse did the planning in the team run: 17 model calls, 4 tool calls | `examples/replay/scenario-muse-team-exceedance/trace.jsonl`, `scripts/demo_contributions.py` |
| S1 to S4 numbers | `examples/replay/scenario-*`, `docs/four-scenario-demo.md` |
| The team reached the same outcome as the deterministic pipeline, at higher cost | `docs/comparative-evidence-report.md` |
| The critic added no detection; the gate stays off | `docs/method-review-validation-results.md`, `docs/method-review-gate-v1.md` |
| Distillation is not adopted | `docs/distillation-results-v1.md` |
| Exact S1 checkpoint reuse has no fair score | `docs/release-acceptance.md` |
| Prithvi Level A: one chip, IoU 0.912, a reproduction | `docs/prithvi-level-a.md` |
| Signed acquisition; 17 of 350 values differ | `docs/muse-family-comparison-run.md` |
| M3: ridge and TCN trained, scored and reloaded in one Muse run | `docs/muse-method-comparison-run.md`, `examples/replay/scenario-muse-method-comparison` |
| Corrected 2015 ablation: no feature group helped | `docs/haze-2015-ablation-results.md` |
| Five prospective predictions, all scored | `docs/prospective-verification.md` |
| The 20-milestone matrix: 16 bounded, 3 partial, 1 future | `docs/vision-matrix-final.md` |
| The hosted entry is replay-only | `docs/hosted-replay.md`, `tests/test_hosted_replay.py` |
| M4: 13 model calls on 2 checkpoints, each named by file and SHA-256 | `examples/replay/scenario-m4-heterogeneous-council/trace.jsonl`, `docs/m4/benchmark-report.md` |
| M5: no supported gain from fire, wind or rain data | `docs/m5/M5_SCIENCE_REPORT.md`, `docs/m5/results/` |
| Each headline value matches its artifact | `docs/release/source_to_screen.csv` |
| Licences and their sources | `LICENSE`, `LICENSING.md` |

## Reproduce

These commands need no model, no key and no network after `uv sync`.

```bash
git clone https://github.com/ysant77/empiraxis.git
```

```bash
cd empiraxis
```

```bash
uv sync --all-extras
```

Check each published run against its manifest and hash chain. Each command exits 0. A changed or missing file exits 1.

```bash
for r in sb05-september sb05b-october live-september-verified live-october-abstained scenario-s1-regression scenario-s2-encoder-reuse scenario-s3-transport scenario-s4-resource-request scenario-muse-team-exceedance scenario-muse-team-regression scenario-muse-method-comparison scenario-m4-heterogeneous-council; do uv run earthlab --data-dir data/nea replay examples/replay/$r || echo "FAILED $r"; done
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

| Item | State on 2026-11-04 | Owner action |
|---|---|---|
| Release commit | `main`. CI passes on `35de956` (M5, PR #118). All 12 published runs replay with exit 0 on a clean checkout. | Confirm the final commit after the open PRs. |
| Open PRs | #117 (M4.1 council, draft) and #116 (film production kit). | Merge only with green CI. |
| Licence | Apache-2.0 for the project code and documents. Data and models keep their own terms (`LICENSING.md`). | none |
| Repository visibility | Public | none |
| Hosted replay | Not published | Optional. Follow `docs/hosted-replay.md`. |
| Video | Voice-only V1.1 fallback exists (no music, SHA-256 `fd54e3d26145…`). Video 2.0 has a watermarked review render and waits for the owner review. | Pick the film and check its SHA-256. |
| Deadline | Planning documents give 4 November 21:00 ET (5 November 10:00 SGT). | Confirm the deadline on the portal. |
| Submission | Not submitted | Submit and keep the receipt. |
