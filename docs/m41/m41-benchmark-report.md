# M4.1 benchmark report (experiment m41-v2)

Date: 2026-11-04. Protocol: `docs/m41/m41-protocol.md` (question, metrics, acceptance) and
`docs/m41/m41-protocol-v2.md` (runs, corrections, Amendments 1 and 2). Runs: 25 main, 2 repeat,
2 stochastic; all 29 traces verify offline. Evidence file:
`docs/m41/evidence/m41-v2-benchmark.json`. Tables: `scripts/m41_tables.py` on that file.

This is an engineering screen with small counts: one run per cell, five packages. It gives
counts, not rates with intervals. It does not claim general accuracy.

## 1. Answer

**The heterogeneous council did not do better than the code rule or a single Muse Lead.**
Arms F (code rule), S (Muse Lead) and T (Muse in all roles) made 5 correct decisions of 5.
Arms H (Llama 3.2 3B data, Qwen3 4B ML, Muse Lead and PM) and HC (H plus a Muse critic) made 4 of 5.
H and HC used more calls, more tokens and more time than S. Under the acceptance rule
(protocol section 10), no council benefit is visible against arm F or arm S on any package.

| Question | Answer from the measured runs |
|---|---|
| 1. Does a single Muse Lead beat the code rule? | No. Both are 5/5 correct and agree with the rule on every package. S raised no known fault and had 7 failed plan checks. |
| 2. Do Llama and Qwen add findings that are not redundant? | Almost none. Llama: 40 findings in H and HC, 0 supported. Qwen: 40 findings, 1 known fault and 1 new supported concern in each arm, 32 unsupported. |
| 3. Do H or HC beat S? | No. H and HC are 4/5. Both abstain on `e-m5-handoff-v2`, where the rule allows `proceed_with_limits` or `request_validation`. |
| 4. Does the critic improve decisions? | No. HC made the same 5 decisions as H. The critic failed the detection and support gates on the 24-case test. |
| 5. Does a gain justify the latency, switching and failure cost? | There is no gain to justify. HC took 91.2 min and 91,601 tokens, against 25.5 min and 14,070 tokens for S. |

## 2. Runs and failures

All 25 main cells ran (F, S, T, H, HC on A, B, C, D and `e-m5-handoff-v2`, temperature 0, seed
20261104). No run failed. No role output failed its contract parse. Every trace (29 with the
repeat and stochastic runs) verifies offline (hash chain, package hash, human gate, executed checkpoints). No disqualifier applies.

Checkpoints (SHA-256 prefix of the model file, the same in every run):

| Checkpoint | Roles | SHA-256 prefix |
|---|---|---|
| Muse Glimmer 30B Q4_K_M (`local-glimmer`) | Lead, PM; all roles in T; critic in HC | `4cc57c0f51040a22` |
| Llama 3.2 3B Instruct (`local-llama-3-2-3b`) | data specialist in H, HC | `6c1a2b4116103267` |
| Qwen3 4B Instruct 2507 (`local-qwen3-4b-2507`) | ML specialist in H, HC | `3605803b982cb64a` |

The Muse critic in HC runs on the Lead's checkpoint. It is a separate role, not an independent
model (`critic_independent_checkpoint` is false in every HC run). Arm HC8 did not run: Llama 3.1
8B failed the critic gates (protocol v2, section 4).

## 3. Decisions (temperature 0)

| Package | F | S | T | H | HC |
|---|---|---|---|---|---|
| a-model-selection-m3 | request_validation ✓ | retain_baseline ✓ | request_validation ✓ | request_validation ✓ | request_validation ✓ |
| b-nea-provenance | proceed_with_limits ✓ | proceed_with_limits ✓ | proceed_with_limits ✓ | request_data ✓ | request_data ✓ |
| c-fire-weather-sufficiency | abstain ✓ | request_data ✓ | abstain ✓ | abstain ✓ | abstain ✓ |
| d-multisource-design-m5 | proceed_with_limits ✓ | proceed_with_limits ✓ | proceed_with_limits ✓ | proceed_with_limits ✓ | proceed_with_limits ✓ |
| e-m5-handoff-v2 | proceed_with_limits ✓ | proceed_with_limits ✓ | proceed_with_limits ✓ | abstain ✗ | abstain ✗ |

On `e-m5-handoff-v2`, the Lead in H and HC did not answer a high ML finding (Qwen, `m1`). The
check `answers_cover_findings` failed. The PM asked for a revision. The HC critic returned
`no_concern` with no findings, so no rebuttal ran.

## 4. Totals per arm (temperature 0, five runs each)

| Arm | Correct | Agrees with rule | Known faults raised by models | Unsupported findings | Failed plan checks | Escalations | Muse calls | Small-model calls | Tokens | Wall min | Load s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| F | 5 | 5 | 0/16 (rule flags 12) | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.0 |
| S | 5 | 5 | 0/16 | 0 | 7 | 7 | 5 | 0 | 14,070 | 25.5 | 0.0 |
| T | 5 | 5 | 1/16 | 27 | 5 | 28 | 23 | 0 | 77,587 | 118.0 | 0.0 |
| H | 4 | 4 | 2/16 | 36 | 3 | 22 | 11 | 10 | 68,479 | 61.4 | 36.0 |
| HC | 4 | 4 | 2/16 | 38 | 4 | 23 | 18 | 10 | 91,601 | 91.2 | 32.8 |

"Load s" is the time to start the side server for the small models (switching cost). The code
rule flags 12 of the 16 known faults in every arm. The models raise at most 2.

## 5. Specialist and critic contributions

| Arm | Role | Checkpoint | Findings | Known fault | New supported concern | Unsupported | Accepted by Lead |
|---|---|---|---|---|---|---|---|
| H | data | Llama 3.2 3B | 20 | 0 | 0 | 20 | 5 |
| H | ML | Qwen3 4B | 20 | 1 | 1 | 16 | 8 |
| HC | data | Llama 3.2 3B | 20 | 0 | 0 | 20 | 2 |
| HC | ML | Qwen3 4B | 20 | 1 | 1 | 16 | 1 |
| HC | critic | Muse (same checkpoint as Lead) | 3 | 0 | 1 | 2 | 3 |
| T | data | Muse | 25 | 1 | 4 | 8 | 17 |
| T | ML | Muse | 21 | 0 | 0 | 19 | 8 |

The Llama data specialist added no supported finding. The Lead accepted 7 of its unsupported
findings. Qwen added one known fault and one new supported concern, with 16 unsupported findings
per arm. Per protocol section 10, the data specialist role adds nothing in this screen. Proposal:
remove it, or call it only for a data-quality question with a code check on each finding.

## 6. Critic test (24 cases: 12 with a seeded fault, 12 clean; scoring m41-v2)

| Critic | Raw detections | Supported detections | High finding on a clean case | Findings | Unsupported | Gates failed |
|---|---|---|---|---|---|---|
| Muse Glimmer (`local-glimmer`) | 3/12 | 1/12 | 3/12 | 54 | 16 | detected, supported |
| Code rules | 6/12 | 6/12 | 0/12 | 16 | 0 | detected |
| Qwen3 4B, contract v2 | 1/12 | 0/12 | 11/12 | 89 | 46 | detected, clean, supported |
| Llama 3.1 8B, contract v2 | 0/12 | 0/12 | 0/12 | 12 | 8 | detected, supported |
| Llama 3.1 8B; Llama 3.2 3B (v1, v2); Qwen3 4B (v1) | 0/12 | 0/12 | 0/12 | 0 | 0 | detected |

No model critic passed all gates. The Muse critic found fewer seeded faults than the code rules
(1 against 6 supported). Per Amendment 3 it stays the default HC critic, and this report states
that it failed. All earlier critic runs are counted.

## 7. Repeat and stochastic runs

| Run | Arm | Package | Temperature | Decision | Correct | Escalations | Failed plan checks | Wall s |
|---|---|---|---|---|---|---|---|---|
| main | H | a-model-selection-m3 | 0.0 | request_validation | yes | 1 | 0 | 733.0 |
| repeat | H | a-model-selection-m3 | 0.0 | request_validation | yes | 1 | 0 | 935.8 |
| main | H | e-m5-handoff-v2 | 0.0 | abstain | no | 8 | 1 | 724.2 |
| repeat | H | e-m5-handoff-v2 | 0.0 | abstain | no | 8 | 1 | 926.6 |
| main | HC | a-model-selection-m3 | 0.0 | request_validation | yes | 1 | 0 | 1345.6 |
| stochastic 1 | HC | a-model-selection-m3 | 1.0 | request_validation | yes | 2 | 0 | 1161.8 |
| stochastic 2 | HC | a-model-selection-m3 | 1.0 | request_validation | yes | 2 | 0 | 961.0 |

The repeats at temperature 0 gave the same decision, the same escalation count and the same
failed check as the main runs. The H error on `e-m5-handoff-v2` is reproducible: the same
`answers_cover_findings` failure occurs again. At temperature 1.0, HC on package A gave the
same decision twice, with one more escalation than at temperature 0. Three runs on one package
do not measure variance in general. Wall times differ by up to about 30% between runs of the
same cell; this machine was swapping during the repeats.

## 8. Number grounding (rule m41-v3, Amendment 2)

Rule m41-v3 also checks integer measurements. It is prospective. The recorded m41-v2 runs keep
their m41-v2 scores. An offline re-check of the 25 main runs with the m41-v3 rule
(`scripts/m41_recheck_numbers.py`, no model call) found new ungrounded integers in 0 runs
(`docs/m41/evidence/m41-v3-number-recheck.json`).

## 9. Limits

- One run per cell. Five packages. Counts only, no intervals.
- The answer keys and the code rule were written by the same project. The F arm agrees with the
  keys by construction on these packages. F is a reference, not an independent model.
- Package D uses the v1 availability rule; package `e-m5-handoff-v2` uses m41-v2 (nominal latency
  with an enforced cutoff). No M5 source has a verified publication time per observation
  (`m5-evidence-5`).
- The Muse critic is not independent of the Lead.
- Wall time depends on one Apple-silicon machine with swap in use. The H repeat on package A
  started at 18:10 SGT and wrote its result at 19:54 during a machine outage. Its recorded
  wall time (935.8 s) is reported as the run recorded it.
- No model computed an environmental result. M5 computed every number in the packages.

## 10. Demonstration run (outside the benchmark)

Arm HC on `e-m5-demo-v3` (merged `m5-evidence-4` @ `35de956` plus the M5-C result), rule
m41-v3, temperature 0. It is outside the benchmark. It has no answer key and no score. Replay:
`examples/assess/replay/20261104T124522Z-HC-e-m5-demo-v3-r1` (30 trace entries, verifies offline).

Question (M5-A): can historical wind, rain, fire activity, imagery and soil moisture improve
Singapore's six-hour PM2.5 predictions beyond PM2.5-only baselines?

- **Code rule (m41-v3).** Allowed: `proceed_with_limits`, `request_validation`. Eligible inputs:
  NEA PM2.5 and IMERG Early. Flags: hindsight inputs (IMERG Final, SMAP, ERA5), unknown
  availability (FIRMS standard processing, IMERG Late) and `overall_deterioration` (fire inputs
  make all-hour MAE worse). Missing facts: HLS clear fraction, SMAP retrieval quality.
- **Council.** Llama (data) made 5 findings and Qwen (ML) made 5. The Lead chose `abstain`
  and did not answer four Qwen findings (`answers_cover_findings` failed). The Muse critic raised
  one high finding: NEA and IMERG Early availability rests on a nominal latency, not a verified
  publication time. It cited only the package id. The Lead accepted it, excluded every input and
  changed the decision to `request_data`. The PM asked for a revision.
- **Outcome.** `request_data` is outside the code rule. The run escalated 7 issues and stopped
  at the human gate. No decision is recorded. Wall time 1,617 s.

The critic repeated the availability correction that the package states as a limit. It did
not find a new fault. Its action (exclude NEA PM2.5 as well) goes further than the evidence:
the M5 result for a PM2.5-lag baseline does not depend on real-time publication of other sources.
This run shows the same pattern as `e-m5-handoff-v2`: the mixed council leaves the code rule
when the Lead does not answer the specialist findings.
