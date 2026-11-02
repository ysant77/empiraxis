# Review-gate validation v1: protocol

Experiment ID: `review-gate-v1`. This is a new experiment. It reuses no benchmark arm, run, prompt or result, and it changes no benchmark record. The case file is `config/benchmark/review_validation.yaml`. This document and that file are frozen before the first live result. A later change gets a new experiment ID.

The gate stays off by default. This experiment does not change the default.

## Question

Does the method review find real method errors or stop unnecessary work, at a measured cost? The number of objections is not the measure.

## Part A: seeded cases

Each case uses inputs that code measures: the real profile, suitability and plan. Only the Lead's case or the decision is seeded. Evaluation reports are the saved reports, and each row records the file digest.

| Case | Truth | Stage | Finding expected |
|---|---|---|---|
| `gru-no-comparison` | fault | before execution | `no_simple_comparison` |
| `elevated-ignored` | fault | before execution | `elevated_not_tested` |
| `elevated-hidden-result` | fault | recommendation | `subgroup_failure` |
| `repeated-refinement` | fault | refinement | `repeated_plan` |
| `era5-as-forecast` | fault | before execution | `hindsight_as_forecast` |
| `prithvi-incompatible` | fault | before execution | `method_blocked` |
| `hybrid-adopt` | fault | recommendation | `adopt_without_gain` |
| `ridge-supported` | sound | before execution | none |
| `ridge-minor-finding` | sound | before execution | `latency_not_named` |

The case `ridge-minor-finding` is sound because code already refuses a plan that breaks the latency. It tests whether the critic and Lead stop a correct plan over a small omission.

Each case has two sides on the same input:

- **Off:** what today's gates refuse with no review. This is computed by code.
- **On:** the review. A case with a material finding and no blocking fault runs the live critic and the live Lead response. It repeats 3 times. Other cases are code only and run once.

## Part B: matched live runs

Three pairs, arm `single`, Muse as Lead, default prompts, one model server, one run at a time: `pm25-regression` gate then plain, `pm25-exceedance` plain then gate, `burned-area-method` gate then plain. In these runs the Lead writes its own case. No test or other heavy job runs on the machine during this part.

## Critic label

Muse is the only approved model that can run in the Lead seat, and small models do not run beside it. So the critic in this experiment is another pass by the same model. Each record has `critic_source`. This is not an independent review.

## Measures

| Measure | Definition |
|---|---|
| Errors detected | Fault cases with the expected finding on the on side, and how many of those the off side also catches. |
| False objections | Sound cases that end `refused` or `needs_revision`, or that raise an unexpected finding. Part B: a critique that a person, after reading it, finds contradicted by the measured inputs. |
| Successful corrections | Answers of `accepted` that code passed: the named finding is gone from the revised case. |
| Rebuttals | Answers of `rebutted` that code passed, and whether a person finds that they address the concern. |
| Open concerns | Runs that end `needs_revision`, with the reason. |
| Avoided work | Saved wall time of the repeated refinements (145 s and 763 s), and Part B work the gate stopped. |
| Cost | Added model calls, tokens and wall time, from the seeded rows and from the Part B pairs. |
| Critic value | Usable concerns against the evaluator's numbers in Part B: supported, not supported, or not testable. A person scores this from the saved text. |

## Acceptance

The proposed limit in `docs/method-review-gate-v1.md` was at most 10% added median wall time and at least one real fault that the run without the gate missed. The owner has not confirmed this limit. So the report gives the numbers next to the limit, and it states no pass. Three pairs give counts only. There is no significance claim.

## Limits, stated before the run

- Seeded cases show what the gate can catch. They do not show how often a Lead makes these errors.
- The scripted tests check the code path. They are not evidence of critic quality.
- Rows on the off side at the recommendation stage record today's rules, read from the saved report. The harness menu did not run for these seeded decisions.
- Timing is one shared Mac under swap pressure.

## Review-gate v2 (set after v1 Part A, before any v2 result)

Experiment ID: `review-gate-v2`. The v1 rows stay as recorded. v1 Part B was not run, because the live v1 rows and a code reading showed two defects that would make Part B uninformative:

1. The critic received strategy names but had to name a method. Two of its submissions failed for this reason, although the concern was correct.
2. The recommendation check treated `not_tested` as a failure. A correct raster `adopt_limited` would have stopped.

Changes: the critic receives `eligible_methods`, the prompt states the rule for `competing_method` and `test.metric`, and only a `failed` claim stops adoption. A failed subgroup claim now joins the limits with the gate on or off.

v2 runs: `gru-no-comparison` 3 times, then Part B as written above. Measures, limits and acceptance text stay as written. The owner still has not confirmed the 10% limit.
