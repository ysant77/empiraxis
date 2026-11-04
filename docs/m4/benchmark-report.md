# M4 benchmark report (experiment m4-het-v1)

Protocol: `docs/m4/m4-protocol.md`, with two amendments. Matrix: `config/benchmark/m4-matrix.yaml`. Raw runs: `~/Documents/meta-ai/m4-runs/` (outside the repo). Per-attempt data: `docs/m4/evidence/m4-attempts.json`.

All runs read validation data only. No run read the sealed test period. Counts are small: 1 to 3 attempts per cell. This report gives counts and no p-values.

## 1. Answer

1. **A council of different checkpoints ran end to end.** Muse served the PM and the Lead. Llama 3.2 3B served both specialists and the critic. Three such runs reached the human gate: primary T-L, primary T-Mc (Llama critic only), secondary T-L. Each has a role-binding record for every seat in the hash-chained trace. `harness-replay` finds 0 mismatches in all 17 attempts.
2. **No claim that the council is better.** Outcomes follow the Lead's sampled choices (GRU or TCN, loss, strategy). The Lead is Muse in every model arm and samples at temperature 1.0. The specialists only call fixed tools, so they cannot change the science.
3. **The small seats were weak.** Qwen3 4B failed the specialist step in 2 of 2 runs. Llama 3.2 3B specialists hit a server error (HTTP 500) in 2 of 3 attempts on the burned-area scenario. The Llama critic gave a usable answer in 1 of 3 live runs, with no finding.
4. **The same-model Muse critic found a real fault** in 2 of 2 primary runs that had it: the Lead wrote "lowest RMSE", and another model has a lower RMSE by 0.002 to 0.004 µg/m³. The independent Llama critic found nothing in any live run.
5. **Llama 3.2 3B in the PM seat failed its check** and was not enabled. The deterministic path (arm F) took 23 s, against 1,639 to 2,287 s for model arms.
6. **The M3 claim is unchanged.** M3 was four roles on one checkpoint. M4 is the first run with different checkpoints in different seats.

## 2. Arms and checkpoints

| Arm | PM | Lead | Specialists | Critic | Distinct checkpoints |
|---|---|---|---|---|---|
| F | none | none | none | none | 0 |
| S-M | none | Muse | none | Muse | 1 |
| T-M | Muse | Muse | Muse | Muse | 1 |
| T-Mc | Muse | Muse | Muse | Llama 3.2 3B | 2 |
| T-L | Muse | Muse | Llama 3.2 3B | Llama 3.2 3B | 2 |
| T-Q | Muse | Muse | Qwen3 4B 2507 | Muse | 2 |
| T-Qr | as T-Q with the reminder prompt | | | | 2 |

| Checkpoint | File | SHA-256 |
|---|---|---|
| Muse Glimmer 30B (Q4_K_M) | `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf` | `4cc57c0f51040a226e5a72cc47b7613f7772950e460a665f7083de89f183f60e` |
| Muse drafter (speculative decoding) | `dflash-Muse-Glimmer-30B-Q4_K_M.gguf` | `b2e808bf656086fe86bd0d0bd990f01d33e377537a07c02d45371517c8b264ef` |
| Llama 3.2 3B Instruct (Q4_K_M) | `Llama-3.2-3B-Instruct-Q4_K_M.gguf` | `6c1a2b41161032677be168d354123594c0e6e67d2b9227c84f296ad037c728ff` |
| Qwen3 4B Instruct 2507 (Q4_K_M) | `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` | `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597` |
| Llama 3.1 8B Instruct (Q4_K_M), critic test only | `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf` | `7b064f5842bf9532c91456deda288a1b672397a54fa729aa665952863033557c` |

Before each server was used, `scripts/m4_preflight.py` read the file name from the running server (`/props`) and compared it with the registry. For Llama 3.2 3B, Qwen3 4B and Llama 3.1 8B it also recomputed the file digest. All matched. For Muse the file name matched. The 16.8 GB Muse file digest was computed on 2026-11-03 for the registry and was not recomputed in the preflight.

Models were served by llama.cpp build b11669 (`620d2225c`). The Muse server was the one already running (context 32,768, temperature 1.0). Each extra server ran alone, with context 16,384, one slot, `--jinja`. The harness samples every seat at temperature 1.0.

## 3. Primary scenario: pm25-method-comparison (the M3 question)

Runs that reached the human gate:

| Arm | Run (UTC id) | Wall s | Model calls | Tokens | Lead choice | Recommendation | Code rule | Checkpoints | Critic |
|---|---|---|---|---|---|---|---|---|---|
| F | `1533d0` | 23 | 0 | 0 | preset (GRU, MAE loss) | adopt_limited: candidate-1 | adopt_limited | 0 | none |
| S-M | `8e9959` | 1,639 | 6 | 13,604 | TCN, MAE loss | retain_baseline: B4 | retain_baseline | 1 | same model: 1 finding |
| T-M | `9f4613` | 2,287 | 15 | 28,028 | GRU, Huber | adopt_limited: candidate-1 | adopt_limited | 1 | same model: 1 finding |
| T-Mc | `c32be1` | 2,168 | 15 | 28,714 | TCN, Huber | adopt_limited: candidate-1 | adopt_limited | 2 | Llama: unusable |
| T-L | `40d596` | 1,848 | 13 | 20,818 | GRU, Huber | adopt_limited: candidate-1 | adopt_limited | 2 | Llama: no concern |

Every run's recommendation equals its own code rule (`code_outcome`). The code rule is computed from that run's evaluator report, so this says the Lead did not argue against the evaluator. It does not say that two runs picked the same model.

Validation scores of the model that each run trained as `candidate-1` (µg/m³ MAE; B4 lagged ridge is 4.680 in every run):

| Arm | candidate-1 MAE | RMSE | MAE above 55 | Skill vs persistence |
|---|---|---|---|---|
| F | 4.588 | 6.416 | 28.772 | 0.160 |
| S-M | 4.739 | 6.484 | 32.377 | 0.130 |
| T-M | 4.572 | 6.383 | 30.298 | 0.163 |
| T-Mc | 4.667 | 6.481 | 30.908 | 0.144 |
| T-L | 4.575 | 6.424 | 29.104 | 0.162 |

Persistence has MAE 5.465 and MAE above 55 of 26.324. Every candidate is worse than persistence above 55 µg/m³, as in M3. The spread between arms (4.572 to 4.739) is the spread of different Lead configurations and different training runs. It does not come from the specialists, which only call fixed tools. The M3 recorded run had TCN 4.711 and B4 4.680.

### Model calls and tokens per role (calls / prompt plus completion tokens)

| Arm | Run | PM | Lead | Data | ML | Critic |
|---|---|---|---|---|---|---|
| T-L (primary) | `40d596` | 2 / 3,888 | 6 / 11,713 | 2 / 1,408 | 2 / 1,699 | 1 / 2,110 |
| T-Mc (primary) | `c32be1` | 3 / 7,753 | 6 / 11,113 | 2 / 2,263 | 2 / 2,809 | 2 / 4,776 |
| S-M (primary) | `8e9959` | - | 5 / 10,343 | - | - | 1 / 3,261 |
| T-M (primary) | `9f4613` | 4 / 8,322 | 6 / 10,892 | 2 / 2,430 | 2 / 2,806 | 1 / 3,578 |
| T-M (secondary) | `35ab8b` | 2 / 3,426 | 4 / 6,204 | 4 / 4,839 | 4 / 5,284 | 1 / 1,591 |
| T-L (secondary) | `e7c3a6` | 3 / 5,316 | 4 / 6,778 | 2 / 1,334 | 2 / 1,417 | 2 / 2,717 |

In T-L the Llama specialists spent 7 s and 5 s of wall time on their calls in the primary run. The Muse Lead spent 1,371 s. Wall time is dominated by Muse (about 4 to 5 tokens per second on a Mac with swap near 25 GB of 25.6 GB). It is not a hardware benchmark.

### What the Llama seats did in T-L (primary)

- Data specialist: called `prepare_data`, then `submit_note`. Two model calls.
- ML specialist: called `train_models`, then `submit_note`. Two model calls.
- Critic: one call, verdict `no_concern`.

These are real model calls to a second checkpoint, and each call produced a typed, code-checked output. The specialist seats have a narrow job by design: they call one fixed tool and write a note. The Lead's choices set the work. State this limit wherever the council is shown.

## 4. Secondary scenario: burned-area-method

| Arm | Run | Status | Wall s | Calls | Recommendation | Code rule | Critic |
|---|---|---|---|---|---|---|---|
| F | `51ca40` | awaiting_human | 1 | 0 | adopt_limited: raster_deterministic | adopt_limited | none |
| T-M | `35ab8b` | awaiting_human | 1,744 | 15 | adopt_limited: raster_deterministic | adopt_limited | same model: no concern |
| T-L | `e7c3a6` (attempt 5 of 5) | awaiting_human | 1,299 | 13 | adopt_limited: raster_deterministic | adopt_limited | Llama: unusable |

T-L attempts 1 to 4 (`82fbbd`, `9b6809`, `15ae00`, `c6bdea`) are in section 5: two server errors and two PM abstentions came before the completed attempt. That is 1 completed run in 5 attempts. The deterministic result is the same in all three arms: September passes the 80 percent valid-land gate, and October does not.

## 5. Every attempt, including failures

Counts for primary and secondary: 17 attempts. 8 reached the human gate (2 of them are arm F).

| Stage | Arm | Run | Status | Wall s | Cause or note |
|---|---|---|---|---|---|
| primary | T-Mc | `64304d` | refused | 1,693 | Method review on (commit `781603d`). Code blocked `unknown_method` and `not_in_plan`. Led to Amendment 1. Not counted as an arm result. |
| primary | T-Mc | `be8ef6` | abstained | 527 | The Lead chose to run no experiment. |
| primary | T-L | `40d596` | awaiting_human | 1,848 | See section 3. |
| primary | T-Mc | `579616` | failed | 797 | The Lead's `choose_strategy` reason was over 400 characters twice. |
| primary | T-Mc | `c32be1` | awaiting_human | 2,168 | See section 3. |
| primary | S-M | `8e9959` | awaiting_human | 1,639 | |
| primary | T-M | `9f4613` | awaiting_human | 2,287 | |
| primary | T-Q | `1f6f19` | failed | 1,005 | Qwen3 4B answered in plain text after `prepare_data`: "data_specialist stopped without submit_note". |
| primary | T-Qr | `2a939b` | failed | 744 | Same fault with the reminder prompt. The reminder fired once. Qwen answered in text again. |
| primary | F | `1533d0` | awaiting_human | 23 | |
| secondary | T-M | `35ab8b` | awaiting_human | 1,744 | |
| secondary | T-L | `82fbbd` | failed | 314 | HTTP 500 from the Llama server on the first data specialist call. |
| secondary | T-L | `9b6809` | abstained | 254 | The PM (Muse) found the request out of scope. |
| secondary | T-L | `15ae00` | failed | 299 | HTTP 500 from the Llama server on the first ML specialist call, after two data specialist calls. |
| secondary | T-L | `c6bdea` | abstained | 180 | The PM (Muse) found the request out of scope. |
| secondary | T-L | `e7c3a6` | awaiting_human | 1,299 | Attempt 5 of 5 for this cell. |
| secondary | F | `51ca40` | awaiting_human | 1 | |

Runs left out of the table because they are not results (folders kept in `~/Documents/meta-ai/m4-runs/`):

- **Crashed, setup error (mine):** a T-Mc attempt crashed after 1,377 s because `EARTHLAB_TRAIN_PYTHON` was not set. All later runs set it to the environment of M3 (torch 2.14.1). A T-L attempt that began right after was stopped by hand.
- **Aborted by hand:** T-L (method review on) before any model call; T-Q attempt 2 and T-Qr attempt 2 after their first attempts failed the same way.

Failures by cause, over the 17 attempts: Lead length limit 1; Lead or PM chose or found no experiment 3; method review refused 1; Qwen no `submit_note` 2; Llama server error 2. Code also refused proposals that a run then corrected: 15 Lead answers over the 400-character reason limit, 5 PM notes over 300 characters, 2 Lead recommendations that named a method the evaluator did not allow, and 6 critic answers with a schema fault (4 echoed `$defs`, 2 without `verdict`). Column "invalid" in `m4-attempts.json` counts them per attempt. M3 shows the same length faults.

## 6. Acceptance gates

| Gate | Result |
|---|---|
| G1 Heterogeneity | **Met.** Runs `40d596`, `c32be1` and `e7c3a6` each have two distinct checkpoint digests, and each checkpoint made at least one model call (`result.json`, `roles`). |
| G2 Integrity | **Met for the runs listed.** Trace chains intact. `harness-replay` shows 0 mismatches for all 17 attempts. No disqualifier occurred. The sealed period was not read. |
| G3 Completion | **Met.** A heterogeneous run reached `awaiting_human`. Failures are reported in section 5. |
| G4 Matched report | **Met with limits.** See section 7. |
| G5 Critic | **Met.** See `docs/m4/critic-report.md`. |
| G6 UI | **Met.** `examples/replay/scenario-m4-heterogeneous-council` loads through `load_run`. Tests cover the adapter, the M4 page and the control view. |

## 7. What this does not show

- **No effect.** One sample per cell, a stochastic Lead at temperature 1.0. The arms differ in the Lead's sampled configuration more than in any seat's checkpoint. Do not read any difference in section 3 as an effect of the council.
- **The specialists add no science.** They call fixed tools. Heterogeneity in these seats shows that a second checkpoint can take part with code checks. It does not show that it adds skill.
- **The independent critic did no useful work live.** In three live runs the Llama critic gave one "no concern" and two unusable answers.
- **Small models at temperature 1.0.** The harness uses one sampling setting for every seat. Qwen3 and Llama 3.2 may do better at a lower temperature. This was not tested because it would change the matched design.
- **Validation years 2019 to 2023 are reused.** Scores are not independent.
- **Qwen provenance.** The Qwen file has no provenance record on disk. Its source repository is not known.
- **Swap pressure.** All wall times come from a shared Mac with swap near its limit.

## 8. Pins

Matrix runs began at commits `781603d`, `5f596d4`, `31b6de2`, `829856b`, `c53597e`, `495d0e3` and `3aba50c`. Each row of `m4-attempts.json` has its commit. Changes between these commits touched tests, examples, documentation and the runner filter. They did not touch run behavior. The final branch head is in `M4_VIDEO_HANDOFF.md`.
