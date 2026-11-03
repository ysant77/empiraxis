# M4 protocol: a council of different checkpoints (experiment m4-het-v1)

Status: pre-registered. This file and `config/benchmark/m4-matrix.yaml` are committed before any M4 matrix result exists. Do not change a stage after its first run. Record a change in a dated "Amendments" section at the end.

## Assumptions (spec not received)

The detailed M4/M5 handoff (`Pasted text(2).txt`) did not reach this session. These sources replace it: the brief `M4_CHILD_SESSION_BRIEF.md`, the Advanced Science Kit of 2026-11-03, the owner's updates of 2026-11-03, and the code. Every assumption is here. An owner-supplied spec overrides them.

| # | Assumption | Why |
|---|---|---|
| S1 | "Heterogeneous" means two or more distinct checkpoint SHA-256 digests in seats that make model calls. Prompts alone do not count. | Brief, priority 3. |
| S2 | The "council" is the existing roles: PM, Lead, data specialist, ML specialist. The critic is a fifth, optional seat. | The repo has these roles and per-role clients. |
| S3 | Muse stays the Lead and the PM. The Lead gate allows Muse only. | Gate in `config/roles/bindings.yaml`; hackathon ruling. |
| S4 | The non-Muse seats are the specialists (Qwen3 4B or Llama 3.2 3B) and the critic (Llama 3.2 3B). | Both passed the specialist preflight in decisions-v1. Qwen is not allowed as a critic by the `qa_reviewer` family gate. |
| S5 | Metrics: completion status, agreement of the recommendation with the code rule (`code_outcome`), model calls, tokens, wall time, refusals, critic validity. No metric of science skill is claimed for the council. | Kit gates V8: claims are typed, abstention is valid. |
| S6 | Acceptance gates are in section 6. They are mine. The spec may set others. | No spec. |
| S7 | One repeat per cell. Counts only, no p-values. | Time budget. |
| S8 | The checkpoint registry holds SHA-256 values computed on 2026-11-03 from the local GGUF files. The Qwen file has no provenance file; its source repository is not known. | Files on disk. |

## Question

Can a council in which different checkpoints serve different seats finish the same workflow as an all-Muse council, with the same deterministic verification, and what does an independent critic add?

This is a feasibility and audit question. It does not ask whether the council is better.

## Arms

All model arms use prompt variant `note-close-v1` and the decision critic. The method review was planned for every arm and is off since Amendment 1. They differ only in which checkpoint serves each seat.

| Arm | PM | Lead | Specialists | Critic | Checkpoints |
|---|---|---|---|---|---|
| F | none | none | none | none | 0 (code only) |
| S-M | none | Muse | none | Muse | 1 |
| T-M | Muse | Muse | Muse | Muse | 1 |
| T-Mc | Muse | Muse | Muse | Llama 3.2 3B | 2 |
| T-L | Muse | Muse | Llama 3.2 3B | Llama 3.2 3B | 2 |
| T-Q | Muse | Muse | Qwen3 4B 2507 | Muse | 2 |

The critic in S-M, T-M and T-Q is a second pass of the Lead's checkpoint. The record says `same_model_second_pass`. The critic in T-Mc and T-L is `independent_model`.

## Scenarios

- Primary: `pm25-method-comparison`, the M3 question. The M3 numbers are the reference.
- Secondary: `burned-area-method`.

Both read validation data only. No run reads the sealed test period.

## What the critic does

- **Method review (before the work).** Code finds material issues in the Lead's case. If it finds some, one critic call and one Lead answer follow. An open concern stops the run for a person.
- **Decision critic (after the evaluator).** The critic reads the evaluator's numbers and the recommendation. It gives up to three findings. Each finding cites evaluator fields with their exact values. Code checks every value. A wrong value, a number that is not in the report, a mention of the sealed period, praise, a cause claim or advice makes code refuse the critique. The model gets one correction.
- **Power.** The critic is advisory. It sets no score, no outcome and no approval. A failed critic call does not stop the run.

## Seeded-fault critic test

Ten labelled cases use the recorded M3 report: five recommendations that the numbers contradict, five that they support. The labels are in `src/earthlab/harness/critic_eval.py` and were written before any critic ran. Code scores each critic:

- **Detected:** a backed finding cites a field that shows the seeded fault.
- **Missed:** a faulty case with no such finding.
- **Clean flagged:** a backed finding on a clean case. This is a concern rate. A true limit of the evidence can be raised on a good case, so it is not an error by itself.
- **Refused attempts:** critic answers that code refused, with the reason.
- **Unusable:** cases where both attempts failed.

## Metrics per run

Status, recommendation and `code_outcome`, model calls and tokens per role, wall time, refusals, critic state and findings, swap use at the start and end, checkpoint digests per seat.

## Disqualifiers

A run is not valid evidence if any of these holds: the trace chain is broken; `harness-replay` finds a mismatch; a seat's checkpoint differs from the registry (the `/props` file name check); the critic changed a number or an outcome; any read of the sealed test period.

## Acceptance gates for M4

| Gate | Pass when |
|---|---|
| G1 Heterogeneity | At least one run has two or more distinct checkpoint digests, each with at least one model call, in `role_binding` records. |
| G2 Integrity | Trace chain intact, replay shows 0 mismatches, no disqualifier. |
| G3 Completion | At least one heterogeneous run reaches `awaiting_human`, or a failure is reported in full. A failed run is a result. |
| G4 Matched report | The table reports every arm with counts, wall time and failures. No effect size. |
| G5 Critic | Rates are reported from the seeded test and from the live runs. |
| G6 UI | The replay of a heterogeneous run loads through `load_run` and the page names the right checkpoints. |

## Limits stated now

- One repeat per cell. The arms differ in more than the checkpoint when a small model fails and the run takes another path.
- Small models are weaker. A lower pass rate for a small seat is expected and is a finding.
- Wall time depends on swap pressure on a shared Mac. It is not a hardware benchmark.
- Validation years 2019 to 2023 are reused. Scores are not independent.
- The seeded cases are synthetic recommendations on one real report.

## Amendments

### Amendment 1 (2026-11-03): method review off

- **What happened.** The first run of `m4-primary` (arm T-Mc, run `20261103T130107Z-64304d`, commit `781603d`) ended with status `refused` after 6 model calls and 1,693 s. Code blocked the Lead's method case with `unknown_method` for `ridge_lagged_log` and `tcn_small`, and with `not_in_plan`. The plan of this scenario names `persistence`, `naive`, `climatology`, `ridge` and `tcn`. No critic call was made, because the findings were blocking.
- **Why.** The method review needs registered method names. The Lead wrote free-text names. This is a fault of the review in this scenario, not a result about the council. The review (an existing gate, off by default) does not fit the M3 scenario without a name map.
- **Change.** `method_review` is `false` in all arms of `config/benchmark/m4-matrix.yaml`. The decision critic stays. The refused run stays in the evidence as result M4-R0. It is not counted as an arm result.
- **Aborted run.** The next planned run (T-L) started with the same setting. It was stopped by hand after the trace showed the council records and before any model call. Its folder is kept with the prefix `ABORTED`.
- **Reruns.** All arms run again under the amended matrix, into a new output folder `primary-b`. The stage and arm names do not change.
