# Review-gate validation: results

Protocol: `docs/method-review-validation-protocol.md`. Revision `review-gate-v1` ran Part A at commit `c5a2835b14f8`. Revision `review-gate-v2` ran one Part A case again and all of Part B at commit `06c090d43e57`. The v1 rows stay as recorded. All runs used Muse Glimmer 30B on one local llama-server, one run at a time.

The critic is a second pass by the same model as the Lead. It is not an independent reviewer.

## Result

The gate stays off by default. The evidence does not support turning it on.

- **Errors detected:** all 7 seeded faults were found, but deterministic rule codes found them. The critic only explained findings that code had already raised. With the gate off, code caught 3 of the 7.
- **False objections:** none on the 2 sound cases. The critic text still contains wrong statements, listed below.
- **Matched live runs:** with the gate on, 1 of 3 runs reached a decision, and it was the same decision as the run without the gate. The other 2 gated runs stopped before execution on method-name and budget rules. Their runs without the gate reached the outcome that the code rule requires. The gate found no scientific fault in these runs.
- **Cost:** on the only pair where both runs reached a decision, the gate added 1469.0 s (2038.7 s against 569.7 s), 3 model calls and 12153 tokens. The proposed limit was at most 10% added median wall time. The owner did not confirm that limit, so this report states no pass. It is far above the proposed limit.
- **Critic value:** the critic added no detection that code did not already make. Its accepted critiques added a ridge baseline to a GRU case. That is a correct change, and the code finding already asked for it.

Three pairs and 18 seeded rows give counts only. There is no significance claim.

## Part A: seeded cases

| Case | Truth | Found with gate on | Found with gate off | Live critic rows | Result of live rows |
|---|---|---|---|---|---|
| `gru-no-comparison`, v1 | fault | yes, `no_simple_comparison` | no | 3 | 2 accepted, 1 unusable |
| `gru-no-comparison`, v2 | fault | yes, `no_simple_comparison` | no | 3 | 3 accepted |
| `elevated-ignored` | fault | yes, `elevated_not_tested` | no | 3 | 2 accepted, 1 left open |
| `elevated-hidden-result` | fault | yes, `subgroup_failure` | yes | 0 | code only |
| `repeated-refinement` | fault | yes, `repeated_plan` | no | 0 | code only, refused |
| `era5-as-forecast` | fault | yes, `hindsight_as_forecast` | no | 0 | code only, refused |
| `prithvi-incompatible` | fault | yes, `method_blocked` | yes | 0 | code only, refused |
| `hybrid-adopt` | fault | yes, `adopt_without_gain` | yes | 0 | code only, needs revision |
| `ridge-supported` | sound | no finding | no finding | 0 | proceed |
| `ridge-minor-finding` | sound | `latency_not_named`, not blocking | no finding | 3 | 1 accepted, 2 unusable; all proceed |

Successful corrections: 8 answers of `accepted` passed code, 5 in v1 and 3 in v2. Rebuttals: 0. Open concerns: 1, `elevated-ignored` v1 run 2, which ended `needs_revision` with no valid Lead disposition. Unusable critiques: 3 of 9 live rows in v1 and 0 of 3 in v2.

The v2 change gave the critic the list of eligible methods. On `gru-no-comparison`, usable critiques went from 2 of 3 to 3 of 3. That is one case and three runs.

Avoided work: the `repeated_plan` rule stopped a repeated refinement that cost 145 s and 763 s in the saved runs. That rule is deterministic code in the gate. The critic did not take part.

Cost of a live critic row: median 871.0 s, 3 calls and 8292 tokens in v1; median 918.4 s, 2 calls and 7453 tokens in v2.

## Part B: matched live runs

| Scenario | Gate | Status | Outcome | Code outcome | Wall s | Calls | Tokens |
|---|---|---|---|---|---|---|---|
| `pm25-regression` | on | awaiting human | retain_baseline | retain_baseline | 2038.7 | 7 | 19781 |
| `pm25-regression` | off | awaiting human | retain_baseline | retain_baseline | 569.7 | 4 | 7628 |
| `pm25-exceedance` | off | awaiting human | retain_baseline | retain_baseline | 1319.5 | 8 | 14753 |
| `pm25-exceedance` | on | refused | none | none | 959.5 | 4 | 8480 |
| `burned-area-method` | on | refused | none | none | 482.2 | 2 | 4705 |
| `burned-area-method` | off | awaiting human | adopt_limited | adopt_limited | 702.5 | 4 | 6500 |

Every run without the gate passed all its acceptance checks and matched the code rule.

Why the gated runs stopped:

- `pm25-exceedance`: the Lead wrote method names as free text, for example "logistic regression with 24h lags" and "persistence alarm", not the registered names `logistic` and `persistence_alarm`. Code refused them as unknown methods. The scientific plan was the same as the plan that ran without the gate.
- `burned-area-method`: the Lead listed two alternatives that are not registered methods. It also asked for 60 s of compute, and the training budget of a deterministic raster path is 0 s. Code refused on both rules. The run without the gate reported September 2015 and held back October 2015, which is correct.
- `pm25-regression`: code raised one non-blocking finding, a number in the data claim that it could not match. The critic answer was unusable, so the Lead gave no response. The run continued and reached the same decision.

These two stops are false stops of the gate: they stopped correct plans over format and budget rules. They are not critic objections, because the critic did not run in those two runs. Under the protocol's definition, Part B has no usable critique, so it has no false objection to count.

## Critique text, scored by a person

These points come from reading the saved critique and Lead text.

- The critic named periods in the sealed test span in its proposed tests: "test split 2024-01-01 to 2026-10-01" and "held-out test years" in v1, and "2026-01-01 to 2026-10-01 holdout" and "2023-2025" in v2. This is wording only. No run read the test period. A gate that is on would need a rule that refuses such a test.
- The critic set thresholds that no evaluator produced, for example an MAE above 55 µg/m³ of 10.0 or 18.0, against a measured persistence value of 26.324. In v2 it turned the case's minimum MAE gain of 0.2 µg/m³ into a skill threshold of 0.2. In one v2 run the Lead copied that into the revised case and changed its success measure. Code passed it. The critic may not set scores, and the evaluator rules did not change, but the revised case text was wrong.
- On `ridge-minor-finding`, v1 run 1 said the features are not realizable at issue time. Code already enforces the latency, so the claim is overstated. It does not count as a false objection under the frozen rule, because the case proceeded.
- The critic and the Lead used the words "health-relevant" in some answers. The system is not a health service.
- An unusable critique leaves a material finding in place, and the run proceeds. This is a known shortcoming.

## Limits

- Seeded cases show what the gate can catch. They do not show how often a Lead makes these errors.
- The scripted tests check the code path. They are not evidence of critic quality.
- Part B has three pairs, one run each, on one shared Mac under swap pressure.
- The gate stops in Part B show a format problem between the Lead's case and the method registry. A fix to that problem would need a new protocol revision and new runs. This release makes no such change.

## Raw records

The rows are local, under the run root, in `earthlab-review-validation/`. Their digests and a copy of every row are in `docs/evidence/comparative-v1.json`, and `docs/comparative-evidence-report.md` section 10 lists the files.
