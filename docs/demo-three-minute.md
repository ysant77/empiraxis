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
| Data preparation, training, baselines | Deterministic code. No model decides a number. |
| Scores and comparison tables | Independent evaluator code |
| S1 to S4 evidence in this script | Deterministic code. No Meta model ran in these four runs. |
| Safety screening of investigation answers | Llama Guard 3 8B, in the investigation path only. It did not run in these harness runs. |
| Approval | A human. No decision is recorded in these runs. |

Print the credit table from the trace of the team run:

```bash
uv run python scripts/demo_contributions.py examples/replay/scenario-muse-team-exceedance
```

## Script

Open the app before recording. Keep one browser tab. The surface control and the scenario pills change the page, and the URL keeps the selection.

| Time | Label | Screen | Say |
|---|---|---|---|
| 0:00 | RECORDED REPLAY | Research Workspace, S1 | EarthLab is an auditable scientific engineering system. A person asks a research question. The system can train a model, reuse one, reject one or ask for evidence. Everything on screen is recorded, and the page says so. |
| 0:20 | RECORDED REPLAY | Control Room, the Muse team run: open it from the Workspace button | Here the local Meta model did the planning. Muse, as PM, checked the scope. Muse, as Lead, chose a statistical method and said why. Code ran the work, and separate code scored it. This table comes from the trace, so a step is credited to Muse only when the trace records it. |
| 0:50 | EXPERIMENTAL RESULT | Scroll to Who took part, or `docs/method-review-validation-results.md` | No critic took part in this run. The method critic is optional and off by default. It is a second pass by the same model, so it is not an independent reviewer. |
| 1:05 | EXPERIMENTAL RESULT | Research Workspace, S1, the charts | S1 is a real experiment on validation years, not a forecast. The GRU beats persistence on MAE, 4.588 against 5.465 µg/m³. Above 55 µg/m³ it is worse, 28.772 against 26.324, so a code rule limits it. |
| 1:30 | EXPERIMENTAL RESULT | Research Workspace, S2 | S2 reused the frozen GRU encoder. Reuse worked and beat logistic regression, 0.255 against 0.162. It lost to the persistence alarm, 0.306. So the system keeps persistence. Rejecting that model is the correct result. |
| 1:50 | EXPERIMENTAL RESULT | Research Workspace, S3, the box table | S3 tests wind, rain and fire with ERA5 hindsight data. No box and level reached consistent, 0 of 6. The evidence is inconclusive, so we name no source. |
| 2:10 | RECORDED REPLAY | Control Room, S4, the human gate | S4 asks for segmentation. The imagery and masks do not fit the study box, so nothing ran and no score exists. The system requests the missing inputs. The gate is pending: no signed approval exists, and nothing can be approved in replay. |
| 2:30 | RECORDED REPLAY | Control Room, the Muse team run, integrity tiles | The trace is hash-chained. The Muse team reached `retain_baseline`, and this matches the code rule. It took 17 model calls and 2157.5 s. The deterministic pipeline reached the same outcome in seconds, so the simpler path stays preferred. |
| 2:50 | LIVE | Terminal | This replay runs now, with no model. It checks the hash chain and recomputes the verified values. |

The LIVE command takes about 10 s. Start it at 2:45, or show the recorded output at 2:50:

```bash
uv run earthlab --data-dir data/nea replay examples/replay/live-september-verified
```

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
uv run --extra ui streamlit run src/earthlab/ui/app.py --server.address 127.0.0.1
```

Check each item:

- [ ] Each replay prints an intact hash chain, and input hashes match.
- [ ] The credit table ends with a pending human decision.
- [ ] Each scenario opens on all three surfaces with the same scenario line: run name, trace head and digest.
- [ ] The table "What is real here" states what ran.
- [ ] The Replay mode line is on every surface.
- [ ] The UI starts with no model server and no `.env` file.

## Recorded fallback

Screenshots of each segment are in `docs/evidence/demo/`. Use them if the interface does not start.

## Limits and negative results

- No model is production-ready. Results are on validation data, and the sealed test period was not read.
- S1 and S2 are simulated-availability hindcasts. The NEA file has no available-at time. They are not forecasts, and they are not a health or hazard warning.
- S3 is a hindsight diagnostic. It is not an attribution.
- S4 has no signed approval. No segmentation ran.
- In the benchmark, the deterministic pipeline had VGC in 4 of 4 runs, single Muse in 3 of 4, and the fixed team prompt in 3 of 3. The baseline team prompt had 0 of 3. Small-model fallback had 0 of 6. DSPy gave no gain. Team arms with mixed models did not run. Timing was contaminated by swap pressure.
- The team has no demonstrated benefit over the simpler arms. See `docs/comparative-evidence-report.md`.
