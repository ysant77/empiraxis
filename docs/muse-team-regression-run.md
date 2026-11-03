# Recorded Muse team run: PM2.5 regression (M2)

One real end-to-end run on 2026-11-03, directed by Muse Glimmer 30B on the local llama-server. It is an extra recorded demonstration. S1 to S4 and M1 did not change.

- **Command:** `earthlab harness pm25-regression --arm team`, at main `43744d9`.
- **Run:** `20261103T014104Z-823499`, outside the repository.
- **Published copy:** `examples/replay/scenario-muse-team-regression`. Model text and reasoning are removed; typed choices and code's checks stay.
- **Offline replay:** 49 trace records, 9 artifacts, 5 models rechecked, 0 mismatches.

## Budget and use

| Item | Budget | Used |
|---|---|---|
| Wall time | 5400 s | 1594.7 s |
| Training time | 1200 s | 0 s for neural training. Ridge and the baselines are fitted in process. |
| Model calls | 40 | 12 |
| Tokens | not capped | 13,565 prompt and 6,219 completion |
| Tool calls | fixed tools only | 2, both run, none refused |

The run has no retries, no provider faults and no human step. No data was downloaded, and the sealed test period was not read.

## The steps

| # | Step | Done by | What happened |
|---|---|---|---|
| 1 | Typed objective and criteria | Code wrote the problem. Muse as PM reviewed the scope. | The scope was accepted on the first call. |
| 2 | Data suitability and acquisition | Code profiled NEA PM2.5 and wrote the suitability checks. | Eligible strategies: deterministic, statistical, small neural, abstain or request. Not eligible: pretrained transfer, fine-tuning, distillation. No acquisition was needed for PM2.5. |
| 2a | NEA wind and rain | A code probe outside the run, not Muse | The archive had wind data for a 2018 date but none for a 2016 date. A full history needs many thousands of paged requests. No rule joins stations to the five regions. They were not used. |
| 3 | Hashes, QA, train-only features | Muse as data specialist called `prepare_data`. Code ran it. | The feature file `5bcf09f8ccc2` was written, and no feature file reaches the test period. |
| 4 | Baseline and model | Muse as Lead chose `statistical`. Muse as ML specialist called `train_models`. Code ran it. | Lagged ridge and four baselines were fitted. The Lead did not choose the eligible neural strategy, so no neural model was trained. |
| 5 | Tuning and time-aware validation | Code | B4 picks its penalty on validation. The run has no separate tuning step. `docs/rolling-origin-ridge-v1.md` measures what that choice adds: 0.017 µg/m³. |
| 6 | Independent scoring and deterministic critique | Evaluator code; recommendation rules | Ridge MAE 4.680, persistence 5.465. Above 55 µg/m³: ridge 30.254, persistence 26.324. |
| 7 | Lead revision | Muse as Lead | Muse first recommended `adopt_limited`. Code refused it ("adopt_limited is not allowed here"): with no challenger beyond the baselines, adoption is not allowed. Muse then recommended `retain_baseline`, which matches the code rule. |
| 8 | Decision, artifacts, trace | Muse as PM forwarded the decision. | The decision waits for a person, with no signed approval. The trace is hash-chained and the artifacts have digests. |

Code also refused two proposals for length: the Lead's first strategy reason and the PM's first forwarding note. Each seat answered once.

## What this run shows

- Muse made the method choice and the recommendation. Code ran every tool, scored every model and refused one recommendation.
- The critique changed the decision: the refusal moved the recommendation from `adopt_limited` to `retain_baseline`.
- The deterministic pipeline reaches the same outcome without a model. The team adds a recorded rationale, not a better result.

## Limits

- The run is one sample.
- Scores are on validation years that many models have already used, so they are not an independent result.
- The same-model critic was off.
- The NEA wind and rain decision was made by a code probe and by the author, not by Muse inside the run. The harness has no acquisition step for these data.
