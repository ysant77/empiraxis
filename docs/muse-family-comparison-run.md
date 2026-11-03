# Muse family-comparison run with signed acquisition

Run `20261103T035551Z-95e7a3`, scenario `pm25-family-comparison`, team arm, provider `local-glimmer` (Muse Glimmer 30B, local). It started at 03:55 UTC and finished at 04:26 UTC on 3 November 2026.

**Status: incomplete against the P1 acceptance list.** Muse chose the statistical strategy, so no neural model was trained in this run. The Lead's critique asked for no revision. Flow 5, the signed acquisition stage, is complete. This document does not combine this run with any other run.

## Stages

| Stage | Actor | What happened | Evidence |
|---|---|---|---|
| Scope | Muse, PM seat | In scope. One call. | `review_scope` in `trace.jsonl` |
| Profile | Runtime | 109k rows of NEA hourly PM2.5, five regions | `artifacts/profile.json` |
| Acquisition | Muse, data seat, then runtime | Muse asked to capture three days: 2023-02-15, 2023-07-15, 2023-11-15. The runtime checked the signed request `nea-pm25-qa-1` and ran the capture. | `artifacts/acquisition.json`, `acquired/nea-pm25.jsonl` |
| Strategy | Muse, Lead seat | First proposal refused: reason over 400 characters. Corrected proposal: `statistical`. | two `proposal_reviewed` records |
| Data | Muse, data seat, then tool | `prepare_data` ran. Features `5bcf09f8ccc2`. | `features-5bcf09f8ccc2.npz` |
| Training | Muse, ML seat, then tool | `train_models` ran the five baselines and the tuned ridge. No GRU, because the strategy was not `small_neural`. | `rolling-origin-ridge.json`, `weights-candidate-ridge-cv.npz` |
| Scoring | Evaluator (code) | Validation years 2019 to 2023 only. The test period was not read. | `artifacts/evaluation-plan-1.json` |
| Critique | Muse, Lead seat | `finish`: no revision asked. | `review_results` record |
| Decision | Muse, Lead seat | `retain_baseline` with model `B4_lagged_ridge`: keep the existing lagged-ridge baseline. It does not mean persistence. | `artifacts/decision.json` |
| Forward | Muse, PM seat | First note refused: over 300 characters. Corrected: forward to a human. The note says that no neural model was compared. | `forward_decision` record |
| Human | Owner | Pending | `human_status: pending` |

Usage: 12 model calls, 13,661 prompt tokens, 7,458 completion tokens, 1,830 s wall time, 0 retries, 0 provider faults, 2 tool calls, 0 rejected tool calls.

## Acquisition (Flow 5)

- **Approval:** the owner signed `nea-pm25-qa-1` with the operator key. The runtime checked the signature, coverage and expiry before the capture.
- **URL:** trusted code built each request URL. Muse gave only the dates.
- **Limits:** 3 requests and 14,865 bytes, under the 1 MB limit. The capture took less than 1 s, under the 120 s limit.
- **Licence:** Singapore Open Data Licence v1.0.
- **Comparison with the local history file:** 333 region-hours match and 17 do not. All 17 are on 2023-11-15, and 10 of them are in the east region. The largest difference is 9 µg/m³ (east at 17:00 and 20:00).
- **Meaning:** the published API and the downloaded history file disagree on one day. The cause is not known. A later revision of the API data is one possible cause. The run did not change the history file.

## Limit enforcement after review

The review of #106 found that the run checked the byte and time limits only before each day's capture. A last day or a later page could pass a limit and still be recorded as acquired. The code now:

- checks the byte limit during each response and stops at the first chunk that passes it;
- checks the time limit before each request, during each response and after the last day;
- gives each request a timeout no longer than the time left;
- writes to a staging log and keeps it as the run's log only when every limit holds;
- checks the proposal again at the execution step, not only in the model seat.

This run stayed inside the limits: 14,865 bytes of 1,000,000, and 0.38 s of 120 s. The new checks would not change its result. The run was not repeated. The 17 differences on 2023-11-15 stay open.

## Tuning

The ridge penalty was chosen on rolling-origin folds inside the train years: 2016, 2017 and 2018. Validation years were not used to choose it.

| Penalty | Mean fold MAE (µg/m³) |
|---|---|
| 1 | 6.107 |
| 10 | 6.105 |
| 100 | 6.090 |
| 1,000 | 6.014 |
| 10,000 | 5.957 |

The search chose 10,000. This is the largest value in the grid. A larger penalty was not tried, so the best value can be above the grid.

## Scores on the validation years

| Model | MAE | Skill vs persistence (95% interval) | MAE above 55 µg/m³ | Evaluator |
|---|---|---|---|---|
| B4_lagged_ridge | 4.680 | 0.142 (0.132 to 0.151) | 30.25 | passes |
| candidate-ridge-cv | 4.697 | 0.138 (0.128 to 0.148) | 30.58 | passes |
| B0_persistence | 5.465 | 0 | 26.32 | reference |
| B1_daily_naive | 5.640 | -0.032 | 32.43 | fails |
| B2_weekly_naive | 6.515 | -0.192 | 41.13 | fails |
| B3_climatology | 7.788 | -0.436 | 46.00 | fails |

Both ridge models are worse than persistence above 55 µg/m³. The decision record states this as a limitation.

## Reload checks

- **Ridge:** the run reloaded the saved weights and compared the predictions. The run did not write that difference to the trace. A later check loaded `weights-candidate-ridge-cv.npz` alone and predicted the validation rows again. The maximum difference from the stored predictions is 0.0. This check was after the run, not in it.
- **Fix:** the runtime now writes a `tuning_verified` trace record with the reload difference, so a future run keeps this evidence.
- **Neural model:** no neural model was trained, so no neural reload check exists.

## Replay

`earthlab harness-replay` on the run folder: 51 records, 10 artifacts, 6 models scored again, 0 mismatches.

## Acceptance list

| Condition | Met | Note |
|---|---|---|
| Muse directs the run | yes | Every choice above came from a Muse seat |
| Signed acquisition with receipt and limits | yes | Flow 5 |
| Neural compared with statistical | **no** | Muse chose `statistical` |
| In-run tuning on temporal folds | yes | Ridge only |
| Checkpoint saved and reloaded | partly | Ridge yes; checked after the run; no neural model |
| Independent scoring | yes | Code evaluator, validation only |
| Critique with one revision | **no** | Muse chose `finish` |
| Decision forwarded to a human | yes | Human decision pending |

## What this run shows

The Lead did not train a neural model. Its reason was that a statistical model fits the time budget and can meet the criteria more simply. That is a valid choice under the objective, which says to keep the simplest method that meets the criteria. The PM seat saw the gap and said in its note that no neural model was compared. So the run is incomplete for the neural comparison, and the agents reported this themselves.
