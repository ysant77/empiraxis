# Scientific Method Review Gate v1

GRU, TCN, tree ensembles, classical regression, hybrids, pretrained models and distillation are candidates, not preferred outcomes. This report records what the saved runs show about method selection. It then describes the gate that this change adds. The gate is off by default. It has no live model run yet, and it does not touch the #75 benchmark, which runs from its own pinned commit.

Sources: saved traces in `earthlab-e1-runs` (`arms`, `bench`, `tiers-live`, `harness-v1`, `mlops-v1`) and the Git history of the rules. Scores are on validation. The test period was not read.

## What the runs show

### 1. Which methods were eligible

| Path | Eligible | How it was decided |
|---|---|---|
| E1 | GRU or TCN as the one candidate. B0 to B4 ran as frozen baselines. | The `Assignment` menu offered only `gru` and `tcn`. No code checked suitability, and the Lead could not choose to train nothing. |
| Tiers | Teacher, direct student, distilled student | Fixed by the tiers protocol. |
| Harness, regression | deterministic, statistical, small_neural, abstain_or_request | `strategy.assess` on measured facts. Distillation was blocked because no repeated workload was declared. Pretrained was blocked because no approved model fits a series. |
| Harness, classification | deterministic, statistical, abstain_or_request | small_neural was blocked: "the classical model must fail first". |
| Harness, raster | deterministic, abstain_or_request | Nothing to fit. |
| S1, S2 families | Fixed lists in `families_run`, filtered by `families.eligible` | Code ran them all. No Lead chose. |

### 2. What the Lead selected, and why

| Path | Live runs | Selection | Stated reason |
|---|---|---|---|
| E1 | 7 | GRU 6, TCN 1 | Window length and log transform for the data. No run argued for a neural model against a simpler one, because the menu did not ask. |
| Harness, regression | 4 | statistical 4 | Enough rows, and lags capture autocorrelation. This strategy has no method menu, so it ran baselines only. small_neural was eligible and was not chosen. |
| Harness, classification | 4 | statistical 4 | A deterministic rule was judged unlikely to beat persistence. |
| Harness, raster | 4 | deterministic 4 | Nothing to fit. |
| Harness, segmentation | 2 | None | The PM ended both as out of scope. |

The harness Lead wrote that a deterministic rule was unlikely to beat persistence. The result went the other way: the persistence alarm F1 was 0.306 and logistic was 0.162. No record tested that statement before the work ran.

### 3. What alternatives were compared

Each E1 run compared one candidate with B0 to B4, and with one sensitivity run in some runs. GRU and TCN never met in one run: they differ only across arms, with different windows. S1 compared persistence, climatology, ridge and trees on the same samples. S2 compared logistic, trees and the frozen hybrid with the persistence alarm. Those two fixed comparisons are the only same-sample method comparisons.

### 4. Whether an independent critique occurred

None occurred before execution. The Lead reviewed its own results, and the PM checked scope and forwarding. The evidence:

- All 7 live E1 runs ended in `adopt_candidate`. Each candidate in the E1 folders was worse than persistence above 55 µg/m³, with MAE 27.25 to 30.30 against 26.32 and recall 0.25 to 0.33 against 0.43. The table held these numbers. No role raised them. The Lead compared with B4 only.
- One PM refused to forward (run `49b577`), but its note agreed with the adoption, so it stated no concern.
- One PM named a contradiction in the decision and forwarded it anyway (run `b0387c`).
- Two classification Leads chose to refine (`b466f5`, `b42d94`). Both cited the evaluator's note that the test period was not read, which is a protocol rule and not a defect. Both then ran the same method with the same configuration. The repeats took 2 min 25 s and 12 min 43 s, from the refine decision to the second evaluation, and they changed no result.

### 5. When each acceptance rule was set

The first E1 evaluation file is from 14:30 SGT on 1 November. A rule set after that time is exploratory until a frozen protocol validates it.

| Rule | Set | Status |
|---|---|---|
| Lower limit of skill above zero, no clear region loss (9.1) | 12:05, before any result | Frozen. The protocol sets it for the test period. Validation use is a rehearsal. |
| Splits, horizons, availability rule, 55 µg/m³ as a diagnostic | 12:05 | Frozen |
| Tier decision rules | 16:11, before any tier result, after E1 | Frozen for tiers |
| Elevated hours decide `adopt_limited` | 17:16 to 17:22 | **Exploratory.** The protocol says this is a diagnostic only, because it conditions on the outcome. |
| Row and rate gates, 30 m resolution limit | 17:16 | Exploratory |
| 35 µg/m³ threshold, F1 gain rule, calibration limit 0.05 | 17:25 | Exploratory |
| 10,000 and 1,000 row limits, "classical must fail first" | 18:00 | Exploratory |
| Tree row limit, 50 positive labels | 20:27 | Exploratory |
| S3 and S4 gate limits | 20:40 | Exploratory |

The 35 µg/m³ threshold came from the train split alone. That protects it from leakage, but it was still chosen after the E1 results.

## The gate

1. **Case.** After the plan exists and before work runs, the Lead submits `MethodProposalV1`: hypothesis, simplest baseline, alternatives, data sufficiency, expected benefit, leakage risks, compute seconds and failure conditions. A placeholder gets one correction.
2. **Code's checks.** `check_proposal` tests every named method against `strategy.assess`, and tests the case against the plan, the budget and the measured profile. A blocking finding refuses the method through the normal refusal path.
3. **One critique.** A material finding starts one critic call, with its one correction. A critic must name a finding and a measurement that can prove it wrong, or name an eligible competing experiment. Praise is refused. An unusable critique changes nothing.
4. **One Lead answer.** A usable critique needs a typed answer, with its one correction, and no more debate. `accepted` carries a revised case, and code checks that the named finding is gone. A revised case on a different method moves the run to that method's plan. `rebutted` names measured facts and the critic's metric. `needs_revision`, or an answer that fails these checks, stops the run before any work with the status `needs_revision`. A person then reviews it and starts a new run.
5. **Claims.** After evaluation, code writes six separate claims. No role can raise one.
6. **Recommendation check.** With the gate on, adoption with a failed gain claim stops at `needs_revision`. With the gate on or off, a failed subgroup claim joins the limitations, so the recommendation cannot hide it.

The critic's and the answer's schemas have no score, status or approval field. The evaluator, the safety gates and the signed human decision do not read it. A refinement that repeats its plan runs nothing.

Turn it on with `run_harness(..., method_review=True)`. The fixed arm has no Lead, so it skips the gate.

## Claims on the saved results

```bash
uv run earthlab method-claims --report <evaluation report> --model <row> --status <registry status>
```

| Claim | S1 ridge | S1 trees | S2 logistic | S2 frozen hybrid |
|---|---|---|---|---|
| Technically feasible | Passed | Passed | Passed | Passed |
| Experimentally tested | Passed | Passed | Passed | Passed |
| Better than baseline | Passed | Passed | Failed\* | Failed\* |
| Robust across subgroups | Failed\* | Failed\* | Failed\* | Failed\* |
| Justified by incremental cost | Not measured | Not measured | Failed | Failed |
| Approved for intended use | Pending human | Pending human | Failed | Failed |

\* Judged under an exploratory rule.

The hybrid is the clearest case. Reuse worked, and its F1 of 0.255 beat logistic at 0.162. It stayed below the persistence alarm at 0.306, and the limits of its gain are −0.165 to −0.001. So reuse was technically successful and adoption was not justified.

S1 ridge and trees pass the frozen rule on validation and fail the exploratory elevated-hour rule. Report both results. Neither one cancels the other.

## How to judge it after #75

The measure is not how often the critic objects. It is whether the review finds real method errors or stops unnecessary work at an acceptable cost. These measures are set now, before any gate result:

| Measure | How |
|---|---|
| Errors found | Paired runs with and without the gate, plus seeded faults: a repeated plan, a blocked method, a baseline that is not the simplest, an unnamed latency, and an untestable failure condition. |
| Critic value | Each usable concern names a measurement. Count the concerns that the evaluator's numbers support, and those they do not. |
| Work prevented | Wall time and model calls of the experiments the gate stopped. |
| Cost | Added wall time, model calls and tokens per run. |

Proposed acceptance, for the owner to confirm before the run: the gate adds at most 10% to median wall time, and it finds at least one real fault that the run without it missed. With so few runs, report counts only and make no significance claim.

## Limits

- The two repeated refinements are a reading of saved traces. The gate has not run live on them.
- All tests use scripted model replies, so the critic's quality is not measured.
- A critic on the same model as the Lead is a separate call, not an independent mind. The record labels it `same_model_second_pass`. A critic on another model is labelled `independent_model`.
- `justified_by_incremental_cost` needs a declared case, so saved runs show `not_measured` unless no gain exists.
- Sample sizes are small, and every result is on validation.

## Contract rules added after review-gate-v2

The v2 runs showed failures in the contract between model text and code. These rules are in `src/earthlab/harness/review_contracts.py`. They change no recorded row. The results file names the classification baseline `persistence_alarm`; the registered name is `persistence`. No live run has used these rules, so a new live experiment needs a new protocol version.

| Failure seen | Rule now |
|---|---|
| The Lead wrote "persistence alarm" and "logistic regression with 24h lags", and code refused both as unknown. | Code maps a registered name, or an alias in a fixed list, to the method. Each alias holds only for the task kinds where the method gives the same output. For example, "persistence alarm" maps to `persistence` in a classification task and is refused in a regression task. The record lists each mapping in `normalized`. Ambiguous names, for example "random forest", stay unknown. |
| "logistic regression with 24h lags" puts a lag window in the method name. | Code still refuses this name. It does not remove the lag text. The refusal says to name the method alone. The lag window is the plan's typed `lags` setting. |
| A deterministic raster plan asked for 60 s, and code refused it against a 0 s training budget. | The training budget applies only to a method that trains. |
| A critic turned a 0.2 µg/m³ MAE gain into a 0.2 skill threshold, and the Lead copied it into the revised case. | A revised case may not change `expected_benefit` or drop a failure condition. A critique threshold must equal a typed criterion for the same metric: the case's minimum gain (metric, unit, validation split), or skill 0, which the evaluator defines as equal to the baseline. Profile counts, years, the event limit, criterion prose and failure-condition prose are not criteria. Zero is not a criterion for MAE. |
| Critics proposed tests on "2026-01-01 to 2026-10-01 holdout" and "2023-2025". | A critique that names the test split, a holdout or the sealed period is refused. The sealed span comes from the registered split of the experiment, by `problem_id`. For the PM2.5 studies it starts on 2024-01-01. The burned-area study has no time split, so a year is not refused there. For a study with no registered split, a critique that names a year is refused. |
| A critic wrote "T+6h test forecasts where true PM2.5 >55 µg/m3". | In `test.samples`, the word "test" alone names the sealed split and is refused. In the claim, "test" can mean an experiment, so only the sealed-period wording is refused there. |

### The rules on saved records

The rules ran offline on every saved v1 and v2 record, with no model call. The records did not change.

| Rule | Saved live text | Result |
|---|---|---|
| Sealed period | 8 critiques named the test period or a year from 2024 | 8 refused |
| Threshold | 6 thresholds had no typed criterion: 0.2 moved from MAE to skill (4), 10 and 18 for MAE above 55 µg/m³ | 6 refused |
| Threshold | 3 tests used skill 0 | 3 passed |
| Fixed success measure | 2 accepted answers changed `expected_benefit` | 2 refused |
| A valid critique | `ridge-minor-finding`, v1 run 1 | passed every rule |

The rules do not remove the two false stops of the gated live runs:

- In `pm25-exceedance`, "persistence alarm" now maps to `persistence`. But "logistic regression with 24h lags" is still refused.
- In `burned-area-method`, the budget rule now passes. But `pixel_sum_no_qa` and `report_no_data` are not registered methods.

A Lead that writes registered names is the missing part. So the gate stays off.

Known gap: MAE above 55 µg/m³ has no typed criterion. Its failure condition compares against persistence, and that value is measured only after the run. So a correct elevated-hour test is refused too.

The gate stays off by default. One critique and one Lead answer stay the limit. The signed decision and the human gate do not change.
