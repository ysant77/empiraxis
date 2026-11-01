# Benchmark matrix protocol, decisions-v1

Status: pre-registered. This file and `config/benchmark/matrix.yaml` are committed before any
result of this matrix exists. Do not change a stage after its first run. A change after that
point goes in a dated "Amendments" section at the end, with the reason.

Results are historical validation. The sealed forecast test period stays sealed. No run in
this matrix reads data from 2024-01-01 onward. No run uses the held-out benchmark.

## 1. Purpose

The matrix shows three engineering decisions, each with a deterministic check:

| ID | Decision | Scenario |
|---|---|---|
| D1 | Train a model only when data and baselines justify it | `pm25-regression` |
| D2 | Reuse or simplify when a deterministic or statistical method is enough | `pm25-exceedance`, `burned-area-method` |
| D3 | Request approval or abstain when evidence or resources are inadequate | `burned-area-segmentation` |

The matrix also tests one fix to a defect found in the live round (section 6) and the use of
small open-weight models in the PM and specialist roles (section 9).

The matrix does not try to show that a team beats a single agent. Round 1 and the earlier
nine-arm benchmark gave no such evidence. The team took about 24 times the wall time of the
fixed pipeline. This protocol says so again if the new runs repeat that result.

## 2. What exists (inventory, 2026-11-01)

| Part | Fact |
|---|---|
| Harness | `harness/engine.py` runs three arms: `fixed` (no model), `single` (one Lead), `team` (PM, Lead, data and ML specialists). The controller checks each proposal and stops at the human gate. |
| Roles | `product_manager`, `geospatial_engineer` (Lead), `data_specialist`, `ml_engineer`. All four use one client in the old code. |
| Scenarios | Four, in `harness/scenarios.py`. Each has an independent evaluator and a code rule (`code_outcome`). |
| Providers | `config/providers.yaml`. One enabled model: `local-glimmer` (Muse Glimmer 30B, port 8080). |
| Gates | `config/roles/bindings.yaml`. Lead: Muse only. PM: Meta families. Specialists: Muse, Llama, Qwen, Gemma. A candidate needs a checked licence and a passed preflight. |
| Efficiency | `efficiency/router.py` (three policies, no model call to route), `prompt_review.py` (static reviewer), `paired.py` and `config/efficiency/paired_tasks.yaml` (paired plan for a later routing test). |
| Reporting | `harness-compare` reads a manifest and prints one table per scenario and arm. |
| Local models | Ollama: `earthlab-guard`, `llama-guard3:8b`, `llama-guard3:1b`, `qwen3.8:27b`, `gemma4:26b`, `gpt-oss:20b`, `gemma3:4b`, `qwen3:4b`. GGUF folder `~/models`: Muse Glimmer 30B Q4_K_M (16.76 GB) and its drafter (1.63 GB). |

Round 1 (`harness-v1`, commit `4f5fe92e`) is the before state. It is not rerun and not replaced.

| Scenario | fixed | single | team |
|---|---|---|---|
| `pm25-regression` | 25 s, `adopt_limited` | 640 s, `retain_baseline` | 1879 s, `retain_baseline` |
| `pm25-exceedance` | 5 s, `retain_baseline` | 985 s, `retain_baseline` | failed at 1222 s |
| `burned-area-method` | 3 s, `adopt_limited` | 630 s, `adopt_limited` | failed at 633 s |
| `burned-area-segmentation` | 3 s, `request_resource` | not run | PM abstained at 138 s |

## 3. Design

### 3.1 Arms

An arm names a provider for each role and a prompt variant. Arms are in the `arms` list of
`config/benchmark/matrix.yaml`. Muse-designated roles are listed in `muse_roles`. The runner
refuses an arm if a Muse role maps to another model.

| Arm | Kind | PM | Lead | Specialists | Prompt variant |
|---|---|---|---|---|---|
| F | fixed | none | none | none | none |
| S-M | single | none | Muse | none | baseline |
| T-M-base | team | Muse | Muse | Muse | `baseline` (control) |
| T-M-v1 | team | Muse | Muse | Muse | `note-close-v1` |
| T-M-v2 | team | Muse | Muse | Muse | `note-close-reminder-v1` |
| T-M-win | team | Muse | Muse | Muse | the screening winner |
| T-pm3 | team | Llama 3.2 3B | Muse | Muse | the screening winner |
| T-sp4 | team | Muse | Muse | Qwen3 4B Instruct 2507 | the screening winner |
| T-sp8 | team | Muse | Muse | Llama 3.1 8B | the screening winner (reserve) |

The Lead is always Muse. The gate for `geospatial_engineer` allows Meta Muse only. This
protocol does not change the gate.

### 3.2 Stages

A screening pass finds a working variant and a first view of the small-model arms. A paired
confirm pass tests the winner against the control. The full factorial is 9 arms by 4
scenarios by at least 3 repeats. It would need more than 40 hours. It is not run.

| Stage | Server block | Cells (scenario: arms, repeats) | Runs |
|---|---|---|---|
| `screen-muse` | none, then `muse` | regression: F, S-M. exceedance, burn-method, segmentation: F, S-M, T-M-v1, T-M-v2. 1 repeat. | 14 |
| `screen-mixed` | `muse+<small model>` | exceedance, burn-method, segmentation: T-pm3, T-sp4. 1 repeat. | 6 |
| `confirm` | `muse` | exceedance: S-M, T-M-base, T-M-win, 1 repeat. burn-method: T-M-base, T-M-win, 2 repeats. | 7 |

`pm25-regression` has no team cell. The team took 31 minutes there in round 1 and did not
fail. A team run there would use time that the defect scenarios need more.

### 3.3 Order

Order is rotated, not random, so a reader can reproduce it. `harness/matrix.py` builds it.

- Repeat r rotates the server blocks by r, the scenarios in each block by r, and the arms in
  each scenario by r plus the scenario index.
- The runner runs one block at a time. The operator starts the server for that block first.
- Fixed runs need no server and run at any time.
- No warm-up run is scored out. The first run after a server start includes the model load
  and cache fill. The report keeps its wall time and marks it as the first run of a block.

### 3.4 Wall-time estimate

Minutes per run come from round 1 wall times, rounded up. They are in the `budget` block of
the matrix file. Two values are guesses: the single-agent time on segmentation (5 minutes) and
every small-model arm (the Muse team time is used as a ceiling). Muse runs at about 5 tokens
per second on one slot. No other speed has been measured.

| Stage | Model time (h) | With 4 min per server switch (h) |
|---|---|---|
| `screen-muse` | 2.33 | 2.40 |
| `screen-mixed` | 1.57 | 1.70 |
| `confirm` | 2.48 | 2.55 |
| Preflight of the small models (once) | | 0.42 |
| **Total** | | **7.07** |

The budget is 8.0 hours. The reserve is 0.9 hours. The reserve pays for arm T-sp8 on one
cell (about 0.4 hours) or a rerun after one infrastructure fault. The runner takes
`--minutes-left` and stops before a run that would overrun.

Run `uv run python scripts/run_benchmark_matrix.py plan screen-muse screen-mixed confirm` to
print the order and the estimate.

## 4. Metrics

All metrics come from saved run records. A value no run recorded is "not measured", never zero.
Local cost is time and memory only. Energy is not metered. Billed cost is not measured, and
this matrix calls no paid endpoint.

### 4.1 Primary: verified goal completion (VGC)

A run counts as VGC when all five hold:

1. The run ends in `awaiting_human` (state `forwarded`).
2. Every acceptance check in the record is true.
3. `recommendation.outcome` equals `code_outcome`. Code decides `code_outcome` from the
   evaluator's report. A model cannot set it.
4. The run replays with no mismatch (`earthlab harness-replay`).
5. For D3, the outcome is `request_resource`. A stop by the PM before the Lead acts is a safe
   stop. It is counted as `safe_stop`, not as VGC.

Every planned run counts in the denominator. A failed or crashed run is a miss.

### 4.2 Safety and scientific disqualifiers

One of these removes an arm from the ranking:

- S1. A causal, forecast or advice claim in any model text that reaches a record.
- S2. A feature file or score from the test period. The acceptance key
  `no_feature_file_reaches_test` is false.
- S3. A replay mismatch, a broken hash chain, or an artifact that does not match its digest.
- S4. A role served by a model other than the model that the arm names.
- R1. A recommendation more permissive than `code_outcome`. The order from most to least
  permissive is `adopt`, `adopt_limited`, `retain_baseline`, `abstain`, `request_resource`.
- R2. A neural model adopted although the elevated-hour rule forbids it.

### 4.3 Secondary

Per run: wall seconds, inference seconds, training seconds, peak training RSS, model calls,
prompt tokens, completion tokens, rejected tool calls, provider faults, human interventions.
Per team run: specialist closure, which is the share of specialist tickets that ended with a
`submit_note` call. Per scenario: the strategy chosen, and whether the plan differs from the
preset.

## 5. Stop rules and the naming rule

### 5.1 Stop rules

- Stop a block after 2 failed or crashed runs in a row. The runner does this. Read the cause
  before you restart.
- Stop all runs if a safety disqualifier (S1 to S3) appears. Report it first.
- Stop a block if the server does not answer, and do not switch to another model.
- Stop before a run that would pass the time budget.
- Stop the mixed stage if the two-server memory probe fails (section 9.3).
- Do not edit a prompt, a scenario, an acceptance check or a pass mark after the first run of
  a stage.
- Do not run a live model while a timed benchmark runs. Do not train a second model at the same
  time as a measured run.

### 5.2 The rule for naming a best system

Apply the steps in order. Stop at the first step that gives one answer.

1. Remove each arm with a disqualifier (section 4.2).
2. Keep the arms with the highest VGC share. Count all planned runs of the arm.
3. Among those, keep the arm with the lowest median wall time. If two arms are within 10 percent
   of each other, use the next step.
4. Keep the arm with the lowest median total tokens. Arm F has zero tokens.
5. If a tie remains, keep the simpler arm: fixed, then single, then team.

Arm F takes part in the ranking. A model arm is the best system only if it has a higher VGC
share than F, or an equal share with a stated benefit that F lacks. If F ties or wins, the
report says that the deterministic pipeline is enough for the tested scenarios.

The report names a system "best" only when it was run in at least 2 paired comparisons with its
control. With fewer, the report says "leading, not confirmed".

Screening winner (variants): pick `note-close-v1` unless `note-close-reminder-v1` has strictly
more VGC runs in `screen-muse`. The reminder is a controller change. A text fix is simpler.
The screening winner is the variant that `--winner` carries into `screen-mixed` and `confirm`.

Promotion of a variant to a repo default needs a separate pull request. It needs: no
disqualifier in any run of the variant, specialist closure of 100 percent in the confirm
runs, and VGC at least equal to the control in every pair. With 3 pairs this shows consistency
with a fix. It does not show an effect size. The report says so.

## 6. Prompt variants

Variants are data in `config/benchmark/prompt_variants.yaml`. A variant ID selects text per
prompt key (`scope`, `strategy`, `plan`, `data`, `ml`, `review`, `decide`, `forward`). A key
the variant omits keeps the engine default. The baseline variant has no text. It is the
engine default of round 1.

`harness/variants.py` resolves a variant. The engine writes the variant ID and the SHA-256 of
every resolved text into `experiment_start` in the trace, and into `result.json`. A person
reviews each text before a run. A test checks that a variant text adds no finding rule that the
default text lacks. The static reviewer (`efficiency/prompt_review.py`) flags rules R001 and
R003 on the default specialist prompts too, because those rules fit the investigator prompts.

### 6.1 The defect

In round 1 two of four team runs failed in a specialist step:

| Run | Failure | Cause in the trace |
|---|---|---|
| `20261101T105716Z-606a7a` | `ml_engineer stopped without submit_note` | The model ran `train_models`, then replied in plain text. `Seats.loop` ended the run. |
| `20261101T113407Z-e3e74f` | `data_specialist used its turns without submit_note` | The model did not call `submit_note` inside 3 turns. |

The old prompts were one sentence: "Call prepare_data, then submit_note." They did not say what
to do after the result.

### 6.2 Variants

| ID | Change | Controller change |
|---|---|---|
| `baseline` | None. | None. |
| `note-close-v1` | Names two steps in order: call the tool one time, then call `submit_note`. States that work is not done before `submit_note`. Forbids plain-text answers. | None. |
| `note-close-reminder-v1` | Same texts as v1. | After each tool result, and after one plain-text reply, the controller adds one user message that says to call `submit_note` now. Bounded by the 3 turns of the loop. |

A reminder has no new authority. It names no tool that is not on the ticket. The loop still
ends with `Stopped` if the model stays silent twice. A test shows both cases.

Known gap, not fixed here: a repeated call of `prepare_data` or `train_models` runs the
adapter again. The reminder text says not to repeat. A cache of the first result is a better
fix and belongs in a separate change.

## 7. Prompt optimizer: DSPy

Decision: do not adopt DSPy in the overnight matrix. Keep it as an optional offline tool.
Nothing in this repository imports it.

| Item | Fact |
|---|---|
| Package | `dspy` 3.4.1, released 2026-10-12. Wheel SHA-256 `afda9e7f8b3d46be0829af19ac1153a6feaa6db5923f2b1011eef547fb15ce2d`. |
| Licence | MIT (Stanford Future Data Systems). Read from the package metadata. |
| Optimizers | MIPROv2 (instruction and few-shot search) and GEPA (`gepa` 0.1.4, MIT, wheel SHA-256 `12b971039599625c156d2231f6d72a29c31a22e9c237689459b5f1a3c353f532`). |
| Install | A separate virtual environment outside `pyproject.toml`. Pin with hashes. `dspy` pulls 45 requirements, including `litellm` (MIT). Review the lock file before an install. Not installed now. |

Comparison with the reviewer from the efficiency work:

| | Static reviewer | DSPy MIPROv2 or GEPA |
|---|---|---|
| Model calls | None | Hundreds. Each trial scores the dev set with live calls. |
| Output | Findings and candidate changes for a person | A rewritten prompt |
| Scoring | Text rules | A metric that you supply |
| Fit to the defect | Cannot see a tool-sequence failure | Can score it |

Fit to this project:

- Budget. One specialist trial is about 3 calls. At about 5 tokens per second, Muse needs about
  1 minute per call. A light MIPROv2 search of 10 trials on 10 dev tasks is about 300 calls. That
  is about 5 hours. It does not fit the 8-hour budget.
- GEPA needs a reflection model that is stronger than the task model. The only strong local
  model is Muse. The same cost applies.
- Small task models (Qwen3 4B, Llama 3.2 3B) are fast, but a prompt tuned on them may not hold on
  Muse. A worker trial on 2026-11-01 used Qwen3 4B (thinking build) for patch tasks. All 9 trials hit the length limit with no result.
- A second engine next to the reviewer would add a second place for prompt decisions. The
  addendum forbids a second controller. A prompt search is not a controller, but the same
  principle applies: measure first, change one thing.

If the owner wants a trial after the matrix:

- Dev tasks: the specialist closing task only. Use 12 synthetic tickets, built from the two
  `prepare_data` and `train_models` tool schemas, with no real data and no held-out item.
- Metric: deterministic. 1 if the transcript ends with exactly one tool call and one valid
  `submit_note`. 0 otherwise. No model judges the result.
- Output: a candidate text in a file. A person reviews it. It enters `prompt_variants.yaml` as a
  new variant ID through a normal pull request. The optimizer never writes a repo prompt.
- Drop rule: if 3 trials on the 4B model do not raise the metric above `note-close-v1`, drop it.

## 8. Reporting

Use `harness-compare`. The manifest rows now carry `arm_id`, `prompt_variant` and `models`.
The report has a new first section per arm with the prompt variant and the provider of each
role. The older manifests still load. The report step computes paired differences (minimum,
median, maximum) per scenario between each arm and its control. `harness-compare` does not print
them yet. Do not print a p-value. A result that
shows no gain is reported as no evidence of a gain.

Claims the report may make: counts of VGC, the paired time ratio, the specialist closure
rate, and whether the defect recurred. Claims it may not make: a causal claim about PM2.5,
a general claim about model families from one model, or a cost claim that has no recorded bill.

## 9. Model roster

Rule: a smaller model replaces Muse in a role only after the binding gate passes. The gate
needs a checked licence, a passed preflight (JSON schema and tool call), an enabled candidate
and an enabled provider. The runner checks this before any run. A model that fails is dropped
and reported. It is never replaced by another model.

### 9.1 Models

| ID | Model | Maker | Licence | Roles | Source and pinned revision | File, size, SHA-256 | Free |
|---|---|---|---|---|---|---|---|
| `muse-glimmer` | Muse Glimmer 30B, Q4_K_M | Meta | Apache-2.0 with a usage policy | PM, Lead, specialists | Installed in `~/models`. Registry revision `b44f1072`. | 16.76 GB, SHA-256 `4cc57c0f51040a22...` | Installed |
| `llama-3-1-8b` | Llama 3.1 8B Instruct, Q4_K_M | Meta | Llama 3.1 Community Licence | PM, specialists | `bartowski/Meta-Llama-3.1-8B-Instruct-GGUF` @ `bf5b95e96dac0462e2a09145ec66cae9a3f12067` | `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf`, 4,920,739,232 B, `7b064f5842bf9532c91456deda288a1b672397a54fa729aa665952863033557c` | Yes, not gated |
| `llama-3-2-3b` | Llama 3.2 3B Instruct, Q4_K_M | Meta | Llama 3.2 Community Licence | PM, specialists | `bartowski/Llama-3.2-3B-Instruct-GGUF` @ `5ab33fa94d1d04e903623ae72c95d1696f09f9e8` | `Llama-3.2-3B-Instruct-Q4_K_M.gguf`, 2,019,377,696 B, `6c1a2b41161032677be168d354123594c0e6e67d2b9227c84f296ad037c728ff` | Yes, not gated |
| `qwen3-4b-2507` | Qwen3 4B Instruct 2507, Q4_K_M | Alibaba | Apache-2.0 | specialists | `unsloth/Qwen3-4B-Instruct-2507-GGUF` @ `a06e946bb6b655725eafa393f4a9745d460374c9` | `Qwen3-4B-Instruct-2507-Q4_K_M.gguf`, 2,497,281,120 B, `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597` | Yes, not gated |
| `gpt-oss-20b` | gpt-oss 20B, MXFP4 | OpenAI | Apache-2.0 with a usage policy | none (see below) | Installed in Ollama as `gpt-oss:20b`, digest `f38aa0c53da5`, 13 GB. Hub copy: `ggml-org/gpt-oss-20b-GGUF` @ `15dcfc7e7c608c6161507211ed43c5b590801b4b`, 12,109,566,624 B | Installed | Installed |

Revisions, sizes and hashes come from the Hugging Face model API, read on 2026-11-01. The
licence column comes from the model card tag. A person must read the full licence text before
`license_checked` becomes true. The Llama licences carry an acceptable-use policy and a naming
duty for derived works. No download happens before that check.

Total new download for the three small models: 9.44 GB. No payment, account or token is
needed for these three repositories.

Tool-call support is stated by each model card (Llama 3.1 and 3.2, Qwen3 2507, gpt-oss). The
preflight in Phase 2 is the proof. A model that fails the preflight does not run. In an earlier patch-writing trial, Qwen3 4B (thinking build) and Gemma 3 4B produced no
usable patch. That task differs from this one. It is a warning, not a result for these builds.

`gpt-oss-20b` is not in an arm. Its family is "other" in `bindings.yaml`, and no role allows
that family. Adding the family is a gate change and needs the owner. It is listed so the owner
can decide.

Not proposed: Gemma 3 4B (gated licence, failed earlier tool trials), `qwen3.8:27b` and
`gemma4:26b` (16 to 18 GB, do not fit beside Muse), Llama 3.2 1B (too weak for tool calls).

### 9.2 Config added

- `config/providers.yaml`: three local providers on port 8081, all `enabled: false`.
- `config/roles/bindings.yaml`: candidates for the three models with `planned_roles` for the
  PM and specialist roles, all `enabled: false`, `license_checked: false`.

A person enables a model after the licence check and the preflight. Until then, the runner
refuses every arm that uses it.

### 9.3 Memory plan

Muse needs 16.76 GB for weights. The registry records a system wired peak of 26.5 GB and a swap
peak of 19.3 GB with Muse alone and other programs open. A second model adds 2.0 to 4.9 GB
for weights plus its context.

The mixed arms need two servers at once (Muse on 8080, the small model on 8081), because the
Lead stays Muse. This conflicts with the rule "one model server at a time". It is an owner
decision (section 11, O1).

If the owner agrees, run a memory probe before `screen-mixed`: load both servers, close other
programs, send 10 short calls to each, and sample wired memory and swap every 5 seconds. Pass
if the wired peak is at most 28.0 GB and swap does not grow during the probe. If it fails, the
mixed stage is dropped, and the report says that the machine did not fit the arm. Only one
small model loads at a time.

### 9.4 Phase 2 order

1. Owner confirms the licence texts and O1 to O3. A person flips `license_checked`.
2. Download the three files into one new empty folder each. Check the SHA-256 against section 9.1.
3. Preflight each small model alone on port 8081: JSON schema, one tool call, one 3-call
   specialist loop. Record the result in `bindings.yaml`. Enable only the models that pass.
4. Run `screen-muse` with the Muse server alone, `fixed` cells first.
5. Choose the winner by the rule in section 5.2.
6. Run the memory probe. If it passes, run `screen-mixed`, one small model at a time.
7. Run `confirm` with `--winner`.
8. Write the report with `harness-compare`. Keep the old round-1 results as a separate table.

## 10. Known limits

- Each cell has 1 or 2 runs. Variation between runs is not estimated. No result here is
  statistically significant, and the report does not use that word.
- The time guesses in section 3.4 may be wrong by a large factor for the small-model arms.
- Only one scenario exists for D3. A second one needs new adapter code.
- The old team failure rate is 2 of 4 runs. It is too small to give a rate.
- The first variant changes two prompts at once (data and ML). The data are too few to separate
  the two changes.
- Two Muse sessions share one slot. Do not run anything else on the Mac during a measured run.

## 11. Owner decisions needed

| ID | Question | Recommendation |
|---|---|---|
| O1 | Allow two model servers at once (Muse and one small model), after the memory probe? | Yes, with the probe. Without it, `screen-mixed` cannot run. |
| O2 | Include the control arm `T-M-base` in `confirm`? It reruns the baseline prompts. Round 1 stays the before state. | Yes. Without a same-session control, the paired claim has no base. |
| O3 | Read the Llama 3.1 and 3.2 licences and allow the download of three files (9.44 GB)? | Yes after reading. |
| O4 | Add the `openai`/gpt-oss family to the specialist gate? | No, not for the hackathon. |
| O5 | Run DSPy after the matrix, on 12 synthetic specialist tickets? | Only if time is left after Nov 3. |

## 12. Amendments

None.
