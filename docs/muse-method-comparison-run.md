# Muse method comparison: tuned ridge and compact neural model

Run `20261103T061204Z-829fed`, scenario `pm25-method-comparison`, team arm, provider `local-glimmer` (Muse Glimmer 30B, local). It started at 06:12 UTC and finished at 06:49 UTC on 3 November 2026, at commit `9b6ec0e`.

**Status: complete for the family comparison.** Muse directed every stage. Trusted tools trained and reloaded a tuned ridge and a compact neural model (TCN). The code evaluator scored both on the same rows. The decision waits for a person. This run does not reuse or merge any other run.

## Research question

Compare persistence, a tuned statistical model and a compact neural model for regional PM2.5 six hours ahead. Decide whether the extra complexity gives enough benefit to adopt, from overall error, elevated-hour error, evaluation reliability and compute cost.

The family scenario of run `20261103T035551Z-95e7a3` trains a neural model only when the Lead chooses the small neural strategy. That Lead chose statistical, so no neural model was trained. This scenario needs both families. When the Lead chooses statistical or small neural, both families are trained. The trace records the Lead's choice as the family it expects to adopt (`family_comparison` record). The Lead still sets the neural configuration, and it can still choose to train nothing.

## Limits declared before the run

| Limit | Value |
|---|---|
| Model calls | 40 |
| Wall time | 5,400 s |
| Neural training time | 1,200 s, estimated before training from measured seconds per epoch |
| Neural configuration | window 24/48/96/168 h; GRU or TCN; hidden 16/32/64; 1 or 2 layers; 3 to 20 epochs; MAE or Huber loss |
| Ridge search | 5 penalties (1 to 10,000), 3 rolling-origin folds on 2016 to 2018 |
| Tools | `prepare_data`, `train_models`. No shell, no code from a model. |
| Network | none. No acquisition ran in this run. |
| Storage | the run folder: 52 MB |

## Stages

| # | Stage | Actor | Result |
|---|---|---|---|
| 1 | Scope | Muse, PM | In scope |
| 2 | Profile and suitability | Code | 109k hourly rows, five regions; code lists the eligible strategies |
| 3 | Data provenance | Code | Source `Historical1hrPM2.5.csv`, SHA-256 `2fb76e1c…5de4`. No new acquisition. |
| 4 | Strategy | Muse, Lead | First answer refused: reason over 400 characters. Second: `statistical` |
| 5 | Neural configuration | Muse, Lead | TCN, hidden 32, 1 layer, window 96 h, log transform, Huber loss, 10 epochs |
| 6 | Preprocessing and features | Muse, data specialist, then tool | Features `3b4b0e36cfae`. Scalers fitted on train years only. Test period not in the file. |
| 7 | Training | Muse, ML specialist, then tool | Baselines, tuned ridge and TCN |
| 8 | Evaluation | Code evaluator | Validation years 2019 to 2023; test period not read |
| 9 | Lead response to evaluation | Muse, Lead | `finish`: no revision |
| 10 | Decision | Muse, Lead | `retain_baseline`, model `B4_lagged_ridge` |
| 11 | Forward | Muse, PM | First note refused: over 300 characters. Second: forward to a person |
| 12 | Human | Owner | Pending |

Usage: 12 model calls, 14,428 prompt tokens, 8,088 completion tokens, 2,223 s wall time, 180 s training, 2 tool calls, 0 retries, 0 provider faults.

## Training

**Tuned ridge (statistical):**

- Penalty chosen on rolling-origin folds 2016, 2017 and 2018, inside the train years.
- Mean fold MAE: 6.107, 6.105, 6.090, 6.014, 5.957 for penalties 1, 10, 100, 1,000, 10,000.
- Chosen: 10,000, the largest in the grid. A larger value was not tried.
- Search time: 0.54 s. Weights `889b6be8…`.

**TCN (neural):**

| Item | Value |
|---|---|
| Architecture | TCN, hidden 32, 1 layer, 10,287 parameters |
| Input | 96 h window, log transform, newest input at T-2 h |
| Optimizer | Adam, learning rate 0.001, batch 256 |
| Loss | Huber |
| Seed | 20261101 |
| Epochs | 8 of 10 run; early stop with patience 3 on validation loss |
| Train loss, epoch 1 to 8 | 0.281, 0.259, 0.255, 0.252, 0.250, 0.248, 0.247, 0.246 |
| Validation loss, epoch 1 to 8 | 0.591, 0.576, 0.598, 0.575, 0.574, 0.580, 0.576, 0.577 |
| Training time | 176.9 s on an Apple M5 CPU, 4 threads, torch 2.14.1 |
| Peak memory | 383 MB |
| Checkpoint | `model.pt`, SHA-256 `af008771…c436c5` |

## Reload checks, recorded in the run

| Model | Check | Result |
|---|---|---|
| Tuned ridge | Predict again from the saved weights file alone | Maximum difference 0.0 (`tuning_verified` record) |
| TCN | Reload `model.pt` in a separate process and predict 43,818 rows again | Hash matches; maximum difference 0.0 (`inference_verified` record) |

## Scores on the validation years, same rows for every model

| Model | MAE | RMSE | Skill vs persistence (95% interval) | MAE above 55 µg/m³ | Evaluator |
|---|---|---|---|---|---|
| B4_lagged_ridge | 4.680 | 6.385 | 0.142 (0.132 to 0.151) | 30.25 | passes |
| candidate-ridge-cv (tuned ridge) | 4.697 | 6.381 | 0.138 (0.128 to 0.148) | 30.58 | passes |
| candidate-1 (TCN) | 4.711 | 6.457 | 0.136 (0.124 to 0.148) | 32.43 | passes |
| B0_persistence | 5.465 | 7.707 | 0 | 26.32 | reference |
| B1_daily_naive | 5.640 | 8.191 | -0.032 | 32.43 | fails |
| B2_weekly_naive | 6.515 | 9.366 | -0.192 | 41.13 | fails |
| B3_climatology | 7.788 | 10.160 | -0.436 | 46.00 | fails |

- **TCN against the ridges:** the TCN does not beat either ridge. Its error above 55 µg/m³ is the largest of the three passing models.
- **Elevated hours:** all three passing models are worse than persistence above 55 µg/m³. The decision record states this for B4.
- **Cost:** the TCN took 177 s to train. The ridge search took 0.54 s.

## Lead response and decision

- **Review:** the Lead read the evaluator's report and chose `finish`. Its reason: B4 has the lowest MAE and the highest skill, and the report gives no defect to correct. No revision ran, and none was forced.
- **Decision:** `retain_baseline` with `B4_lagged_ridge`. This keeps the existing lagged ridge. It does not mean persistence.
- **Forward:** the PM forwarded the decision to a person.
- **Optional LLM critic:** off, as in every release run.

## Faults in the agents' text

- **Speed claim:** the Lead said the TCN "trains fast vs GRU". The code's own table gives 50 s per epoch for a TCN and 4 s for a GRU at window 48, so the claim is not correct. This TCN took 22 s per epoch at window 96.
- **Elevated hours:** the PM note says the candidates are worse than persistence above 55 µg/m³. That is true, but B4 is worse too, and the note does not say so. The decision record does.
- **Length limits:** two answers were refused for length and corrected on the retry.

## Limits of this evidence

- **Reused validation years:** 2019 to 2023 were used in many earlier experiments. This is not an independent score.
- **Neural head start:** the TCN chose its best epoch on validation loss over the same years it is scored on. The ridges did not. This gives the TCN a small advantage, and it still did not win.
- **One seed, one configuration:** no claim about neural models in general.
- **Edge of the grid:** the ridge penalty is at the top of its grid.
- **Sealed test period:** still not read.

## Data provenance

This run made no request to any network. It read the local NEA history file, SHA-256 `2fb76e1c…5de4`. The signed acquisition of run `20261103T035551Z-95e7a3` checked that file against the official API for three days. It found 333 matching region-hours and 17 that differ, all on 2023-11-15. Those differences are still unexplained, and this run did not change the file. That receipt belongs to the earlier run, not to this one.

## Replay

`earthlab harness-replay`: 52 records, 9 artifacts, 7 models scored again, 0 mismatches.
