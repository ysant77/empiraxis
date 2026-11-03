# Three-minute demonstration

Every number in this script comes from a saved file. The demonstration downloads nothing, trains nothing and calls no model. One live Muse run takes 10 to 35 minutes on the development Mac, so model work appears as a recorded replay and says so.

Each segment has one label:

- **LIVE:** runs in front of the viewer. In this script, that is deterministic code only.
- **RECORDED REPLAY:** a saved real run, read from its hash-chained trace.
- **EXPERIMENTAL RESULT:** saved evidence from a historical experiment on validation data.

## What Meta's model did

Muse Glimmer 30B ran locally, served by llama-server. It did the steps below, and the trace records each one as a proposal that code checked.

| Step | Done by |
|---|---|
| Scope check and forwarding note | Muse Glimmer, product manager seat |
| Strategy, method choice, review of results, recommendation | Muse Glimmer, Lead seat |
| Method critique, when the gate is on | Muse Glimmer, a second pass by the same model. It is not independent. |
| Calls to the fixed data and training tools, short notes | Muse Glimmer, data and ML specialist seats |
| Data preparation, training, baselines | Deterministic code. No model decides a number. |
| Scores and comparison tables | Independent evaluator code |
| S1 to S4 evidence in this script | Deterministic code. No Meta model ran in these four runs. |
| Safety screening of investigation answers | Llama Guard 3 8B, in the investigation path only. It did not run in these harness runs. |
| Signed approvals | The owner, with the operator key: the NEA acquisition, the Prithvi weights and chips, and the prediction ledger |
| Model adoption | A human. The decisions of the team runs are still pending. |

Print the credit table from the trace of the team run:

```bash
uv run python scripts/demo_contributions.py examples/replay/scenario-muse-team-exceedance
```

## Script

Open the app before recording. Keep one browser tab. The surface control and the scenario pills change the page, and the URL keeps the selection.

Recording plan: capture the screen without sound, then record the voiceover separately. Each segment uses the existing Research Workspace, Engineering Lab or Control Room.

| Time | Label | Screen | Say |
|---|---|---|---|
| 0:00 | RECORDED REPLAY | Research Workspace, M3 | Empiraxis is a scientific engineering team run by a Meta model. A person asks a research question. Muse Glimmer plans the work, trusted tools run it, separate code scores it, and a person decides. |
| 0:15 | RECORDED RUN | `docs/muse-family-comparison-run.md`, acquisition table | Muse, as data scientist, asked to check the local NEA file against the official API for three days. The owner signed the request. Code built every URL and enforced the limits: 14,865 bytes. 333 values matched. 17 did not, all on 15 November 2023. The new data found a data-quality problem; it did not just add rows. |
| 0:40 | RECORDED REPLAY | Engineering Lab, M3, family table | In a second run, Muse as Lead expected a statistical model to win, and set up a compact neural model. Tools trained both: a ridge tuned on rolling train folds, and a TCN, 8 epochs in 177 seconds. Both reloaded with zero difference. |
| 1:00 | RECORDED REPLAY | Control Room, M3, decision | The evaluator scored all models on the same rows. The TCN did not beat the ridge, and all models are worse than persistence above 55 µg/m³. The Lead kept the lagged ridge. The decision now waits for a person. |
| 1:20 | EXPERIMENTAL RESULT | `docs/haze-2015-ablation-results.md`, scores table | For the 2015 haze, we added ERA5 wind and rain, then FIRMS fire detections, to PM2.5 history. Neither helped. A review found a scaling leak and a short fire window; we fixed both and ran it again. The result is still negative, and we report it. |
| 1:45 | EXPERIMENTAL RESULT | `docs/evidence/prithvi-level-a.png` | With a signed approval, we ran the pretrained Prithvi burn-scar model once on one published chip. IoU 0.912. This is a reproduction, not a transfer result. |
| 2:05 | RECORDED RUN | `docs/prospective-verification.md`, table | The owner signed a prediction ledger. Five predictions were issued at 10:45, before their 16:00 target hour, then scored only against values NEA had published by the check time. All five were scored. The mean absolute error is 7.2 µg/m³. Five values are not evidence of forecast skill. |
| 2:30 | RECORDED REPLAY | Control Room, M3, integrity tiles and human gate | Every step is in a hash-chained trace. On the full local run, a replay with no model scored all seven models again with zero mismatches. Nothing is adopted until a person approves it. |
| 2:50 | LIVE | Terminal | This check runs now, with no model. It verifies the hash chain and every published file digest. |

The LIVE command takes about 10 s. Start it at 2:45, or show the recorded output at 2:50:

```bash
uv run earthlab --data-dir data/nea replay examples/replay/scenario-muse-method-comparison
```

The published copy leaves out 8 files, so this command checks digests and does not score again. The full run folder is local; `earthlab harness-replay <run folder>` scores it again.

## Required local assets

All of these are in a clone of the repository: `data/nea/`, `examples/replay/`, `config/` and `docs/`. The demonstration needs no model weights, no Earth Engine access, no API key and no network after `uv sync`.

## Clean-clone checklist

```bash
git clone git@github.com:ysant77/axiom-earthlab.git
```

```bash
cd axiom-earthlab
```

```bash
uv sync --all-extras
```

```bash
uv run earthlab --data-dir data/nea replay examples/replay/live-september-verified
```

```bash
uv run earthlab --data-dir data/nea replay examples/replay/live-october-abstained
```

```bash
uv run python scripts/demo_contributions.py examples/replay/scenario-muse-team-exceedance
```

```bash
uv run earthlab --data-dir data/nea replay examples/replay/scenario-muse-team-exceedance
```

```bash
uv run earthlab --data-dir data/nea replay examples/replay/scenario-muse-method-comparison
```

```bash
uv run --extra ui streamlit run src/earthlab/ui/app.py --server.address 127.0.0.1
```

Check each item:

- [ ] Each replay prints an intact hash chain, and input hashes match.
- [ ] The team run replay says the manifest matches and names the 11 files that the redacted copy leaves out.
- [ ] The credit table ends with a pending human decision.
- [ ] Each scenario opens on all three surfaces with the same scenario line: run name, trace head and digest.
- [ ] The table "What is real here" states what ran.
- [ ] The Replay mode line is on every surface.
- [ ] The UI starts with no model server and no `.env` file.

## Recorded fallback

Screenshots of each segment are in `docs/evidence/demo/`. Use them if the interface does not start. They were taken at 1440 by 900 from the release build. Tablet (768 by 1024) and phone (390 by 844) views of the same pages are in `docs/evidence/screens/`.

## Limits and negative results

- No model is production-ready. Results are on validation data, and the sealed test period was not read.
- S1 and S2 are simulated-availability hindcasts. The NEA file has no available-at time. They are not forecasts, and they are not a health or hazard warning.
- S3 is a hindsight diagnostic. It is not an attribution.
- S4 has no signed approval. No segmentation ran.
- In the benchmark, the deterministic pipeline had VGC in 4 of 4 runs, single Muse in 3 of 4, and the fixed team prompt in 3 of 3. The baseline team prompt had 0 of 3. Small-model fallback had 0 of 6. DSPy gave no gain. Team arms with mixed models did not run. Timing was contaminated by swap pressure.
- The team has no demonstrated benefit over the simpler arms. See `docs/comparative-evidence-report.md`.
