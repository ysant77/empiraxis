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

| Arm | Kind | PM | Lead | Specialists | Prompt variant | Ranked |
|---|---|---|---|---|---|---|
| F | fixed | none | none | none | none | yes |
| S-M | single | none | Muse | none | baseline | yes |
| T-M-base | team | Muse | Muse | Muse | `baseline` (control) | yes |
| T-M-v1 | team | Muse | Muse | Muse | `note-close-v1` | yes |
| T-M-v2 | team | Muse | Muse | Muse | `note-close-reminder-v1` | yes |
| T-M-win | team | Muse | Muse | Muse | the screening winner | yes |
| T-pm3 | team | Llama 3.2 3B | Muse | Muse | the screening winner | yes |
| T-sp4 | team | Muse | Muse | Qwen3 4B Instruct 2507 | the screening winner | yes |
| T-sp4-tuned | team | Muse | Muse | Qwen3 4B Instruct 2507 | `qwen-tuned-v1` (section 7) | yes |
| T-sp8 | team | Muse | Muse | Llama 3.1 8B | the screening winner (reserve) | yes |
| S-q4 | single | none | Qwen3 4B | none | baseline | **no** |
| S-l3 | single | none | Llama 3.2 3B | none | baseline | **no** |

The Lead is Muse in every ranked arm. The gate for `geospatial_engineer` allows Meta Muse
only. This protocol does not change the gate. Arms S-q4 and S-l3 are the fallback of section
9.3. They put a small model in the Lead seat with no Muse server up. They do not meet the
Lead gate. The runner checks them in the specialist gate instead. They carry `ranked: false`,
the manifest records it, and the report prints "no: Lead gate waived". They are never named a
best system.

### 3.2 Stages

A screening pass finds a working variant and a first view of the small-model arms. A paired
confirm pass tests the winner against the control. The full factorial is 12 arms by 4
scenarios by at least 3 repeats. It would need more than 40 hours. It is not run.

Default path, if the memory probe passes: `screen-muse`, `tune-prompt`, `screen-mixed`,
`screen-tuned`, `confirm`.

| Stage | Server block | Cells (scenario: arms, repeats) | Runs |
|---|---|---|---|
| `screen-muse` | none, then `muse` | regression: F, S-M. exceedance, burn-method, segmentation: F, S-M, T-M-v1, T-M-v2. 1 repeat. | 14 |
| `tune-prompt` | Qwen3 4B alone | Offline prompt tuning on 12 synthetic tickets (section 7). No scenario runs. | 0 |
| `screen-mixed` | `muse+<small model>` | exceedance: T-sp4. burn-method, segmentation: T-pm3, T-sp4. 1 repeat. | 5 |
| `screen-tuned` | `muse+qwen` | burn-method, segmentation: T-sp4-tuned. 1 repeat. | 2 |
| `confirm` | `muse` | exceedance: T-M-base, T-M-win. burn-method: T-M-base, T-M-win, 2 repeats. | 6 |
| `fallback-single` | one small model alone | Only if the probe fails. exceedance, burn-method, segmentation: S-q4, S-l3. 1 repeat. It replaces `screen-mixed` and `screen-tuned`. | 6 |

`pm25-regression` has no team cell. The team took 31 minutes there in round 1 and did not
fail. A team run there would use time that the defect scenarios need more.

`T-M-base` is the same-session control (owner decision, 2026-11-01). Round 1 stays the before
state. The control runs the baseline prompts with the tool-call cache (section 6.2), so it
differs from round 1 in that one controller change.

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
the matrix file. Three kinds of value are guesses: the single-agent time on segmentation (5
minutes), every small-model arm (the Muse time is used as a ceiling), and the tuning stage (50
minutes, section 7). Muse runs at about 5 tokens per second on one slot. No other speed has
been measured.

| Stage | Model time (h) | With 4 min per server switch (h) |
|---|---|---|
| `screen-muse` | 2.33 | 2.40 |
| `tune-prompt` | 0.83 | 0.83 |
| `screen-mixed` | 1.20 | 1.33 |
| `screen-tuned` | 0.42 | 0.48 |
| `confirm` | 2.20 | 2.26 |
| Preflight of the small models (once) | | 0.42 |
| **Default path total** | | **7.72** |
| Fallback path (`fallback-single` instead of the two mixed stages) | | 7.14 |

The budget is 8.0 hours. The reserve on the default path is 0.28 hours. That is one rerun of
a short cell. Arm T-sp8 does not fit and runs only if an earlier stage is dropped. The runner
takes `--minutes-left` and stops before a run that would overrun. If `tune-prompt` or
`screen-muse` runs over, drop `screen-tuned` first, then the second repeat in `confirm`.

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

0. Leave out each arm with `ranked: false`.
1. Remove each arm with a disqualifier (section 4.2).
2. Keep the arms with the highest VGC share. Count all planned runs of the arm.
3. Among those, keep the arm with the lowest median wall time. If two arms are within 10 percent
   of each other, use the next step.
4. Keep the arm with the lowest median total tokens. Arm F has zero tokens.
5. If a tie remains, keep the simpler arm: fixed, then single, then team.

Arm F takes part in the ranking. Unranked arms are reported in their own table. A model arm is the best system only if it has a higher VGC
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

Tool-call cache (commit `72715a6`): a repeated call of `prepare_data` or `train_models` used
to run the adapter again. The ticket handler now runs the adapter once and returns the first
result to a repeated call. It applies to every arm, including the control. A scripted test
shows one adapter run for two model calls. Round-1 team times include such repeats, so the new
team times are not directly comparable. The report says so.

## 7. Prompt optimizer: DSPy

Decision (owner, 2026-11-01): keep DSPy as an offline developer tool, run it after
`screen-muse` on Qwen3 4B Instruct, not on Muse. It measures a "before" and an "after" score.
Nothing in `src/` imports it, and `pyproject.toml` does not list it.

| Item | Fact |
|---|---|
| Package | `dspy` 3.4.1, released 2026-10-12, MIT (Stanford Future Data Systems). Wheel SHA-256 `afda9e7f8b3d46be0829af19ac1153a6feaa6db5923f2b1011eef547fb15ce2d`. |
| Optimizer | MIPROv2 in instruction-only mode (no demos). GEPA 0.1.4 (MIT) is in the lock for a later trial. |
| Environment | `~/Documents/meta-ai/prompt-optimizer-env`, outside the repo. Built from `tools/prompt_optimizer/requirements.lock` with `--require-hashes`: 66 packages, including `litellm` 1.106.6 (MIT) and `openai` 2.54.0. `import dspy` and `from dspy.teleprompt import MIPROv2, GEPA` work. |
| Tool | `tools/prompt_optimizer/optimize.py`. `--dry-run` needs no model and passes. The live run has not been made. |

Comparison with the reviewer from the efficiency work (`efficiency/prompt_review.py`). The
reviewer is static and calls no model. It flags missing constraints and contradictions, and a
person applies each change. It cannot see a tool-sequence failure. DSPy scores a prompt by live
calls and proposes new text. The two do not overlap. This is not a second controller: it does
not run in the product, and it does not change a repo prompt. A candidate enters the repo
only as a new variant ID after a person has reviewed the text.

Fit and cost:

- On Muse, a light search needs about 300 calls, about 5 hours. That does not fit. On Qwen3 4B
  the guess is 50 minutes in total (guess, not measured): 8 trials on 8 training tickets,
  proposer calls, and three held-out scores. Its server is up on port 8081 alone, so Muse is not
  loaded.
- Weakness: a prompt tuned on a 4B model may not hold on another model. The candidate is only
  used in arm T-sp4-tuned, with Qwen3 4B in the specialist role.
- Drop rule: if the candidate does not beat both the default text and `note-close-v1` on the
  4 held-out tickets, drop it and say so. Skip `screen-tuned`.

Dev tasks: `config/benchmark/specialist_dev_tickets.yaml`. Twelve synthetic tickets, 6 for
each specialist role, built from the tool schemas. They hold no PM2.5 data, no held-out item
and no test-period value. Tickets 01 to 04 of each role train. Tickets 05 and 06 stay out for
the final score.

Metric: `closes_cleanly` (`harness/closure.py`). It is 1 when the transcript holds exactly one
ticket-tool call, then one `submit_note` call, and nothing else. A test keeps the tool's copy
equal to the repo's. No model judges the result.

Output: `candidate.json` with the candidate text, three held-out scores (default, `note-close-v1`,
candidate), the SHA-256 of the text and of the lock file, and `needs_review: true`.

Use of the candidate: a person reads the text and adds it to `prompt_variants.yaml` as
`qwen-tuned-v1`. The runner refuses `T-sp4-tuned` until that variant exists. This is the review
gate. The "before" evidence is the held-out score of the default text. The "after" evidence is
the held-out score of the candidate and the `screen-tuned` runs. With 4 held-out tickets and 2
runs, the report states the counts and no more.

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

Download status (2026-11-01): the Qwen3 4B file is downloaded to
`~/Documents/meta-ai/models-bench/qwen3-4b-instruct-2507-gguf/` at the pinned revision. Its size
(2,497,281,120 B) and SHA-256 match this table. The owner approved this Apache-2.0 file. The two
Llama files are not downloaded. They need the owner to accept the Llama licence. No payment,
account or token is needed for any of the three repositories.

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

The owner kept the rule: mixed arms stand only if the memory probe passes. The server rule
does not change. Run the probe before `screen-mixed`: load both servers, close other programs,
send 10 short calls to each, and sample wired memory and swap every 5 seconds. Pass if the wired
peak is at most 28.0 GB and swap does not grow during the probe. Only one small model loads at
a time.

Fallback if the probe fails: drop `screen-mixed` and `screen-tuned`. Run `fallback-single`. It
tests each small model alone in a single-agent arm (S-q4, S-l3), with no Muse server up. These
arms do not meet the Lead gate. Their label is "Lead gate waived". They are never ranked and
never named a best system. They show only whether a small model can complete the scenarios by
itself. Without Muse, the Lead seat has no gate-approved model, so a pass there does not
authorise the small model for the Lead role. S-l3 needs the Llama licence and download first.
The report says that the machine did not fit the mixed arms.

### 9.4 Phase 2 order

1. Done: Qwen3 4B downloaded and verified. A person reads the licence texts and flips
   `license_checked`. The owner accepts the Llama licences before those files download.
2. Preflight each small model alone on port 8081: JSON schema, one tool call, one 3-call
   specialist loop. Record the result in `bindings.yaml`. Enable only models that pass.
3. Run `screen-muse` with the Muse server alone, `fixed` cells first.
4. Choose the winner by the rule in section 5.2.
5. Run `tune-prompt` with Qwen3 4B alone. A person reviews the candidate and adds
   `qwen-tuned-v1`, or drops it.
6. Run the memory probe. If it passes, run `screen-mixed` and `screen-tuned`, one small model at
   a time. If it fails, run `fallback-single`.
7. Run `confirm` with `--winner`.
8. Write the report with `harness-compare`. Keep the round-1 results as a separate table.

## 10. Known limits

- Each cell has 1 or 2 runs. Variation between runs is not estimated. No result here is
  statistically significant, and the report does not use that word.
- The time guesses in section 3.4 may be wrong by a large factor for the small-model arms.
- Only one scenario exists for D3. A second one needs new adapter code.
- The old team failure rate is 2 of 4 runs. It is too small to give a rate.
- The first variant changes two prompts at once (data and ML). The data are too few to separate
  the two changes.
- Two Muse sessions share one slot. Do not run anything else on the Mac during a measured run.

## 11. Owner decisions (answered 2026-11-01)

| ID | Question | Answer |
|---|---|---|
| O1 | Two servers at once? | Only if the memory probe passes. The server rule is unchanged. Fallback in section 9.3. |
| O2 | Include `T-M-base` in `confirm`? | Yes. |
| O3 | Download of the model files | Qwen3 4B (Apache-2.0): approved and done. Llama files: wait for the owner to accept the licence. |
| O4 | Add the gpt-oss family to the gate? | No. |
| O5 | DSPy | Yes, offline, on Qwen3 4B, with person review (section 7). |

Open: the owner must accept the Llama 3.1 and 3.2 licences before arms T-pm3, T-sp8 and S-l3
can run. Without them, those arms are dropped and the report says so.

## 12. Amendments

None. The edits of 2026-11-01 (second revision: control in `confirm`, tuning stage,
fallback arms, tool-call cache) were made before any stage started.
