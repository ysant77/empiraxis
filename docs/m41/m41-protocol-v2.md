# M4.1 protocol, version 2 (experiment m41-v2)

Status: frozen on 2026-11-04, before any m41-v2 council run and before the rescoring of the
recorded critic runs. Protocol m41-v1 (`m41-protocol.md`) with Amendments 1 to 3 stays
unchanged. Version 2 keeps everything in version 1 except the corrections below.

## 1. Why a new version

An independent review of the draft found defects in scoring and eligibility after the critic
test had started. Results scored under version 1 stay in the record. Every affected result is
scored again, or run again, under version 2 and written to a new file.

## 2. Corrections

| # | Area | m41-v1 | m41-v2 |
|---|---|---|---|
| 1 | Critic detection | A finding with the seeded fault class counts. | It counts only when the finding also passes the code check and cites at least one id that the seeded fault concerns (`examples/assess/critic-case-evidence.json`). Raw and evidence-backed counts are both reported. The gates use evidence-backed counts. |
| 2 | M5 availability | Issue-time valid when M5 classes the source so and its nominal latency is at most 24 h. | Also needs an M5 feature that enforces the input cutoff, and an archive that is the product published at issue time. A timely product that fails these is `unknown`. Unknown is never a forecasting input. Each source records `availability_basis` and `input_cutoff_hours`. |
| 3 | Package E references | The design rule cites `t19.R2_vs_R1.skill`, which package E did not have. | Package `e-m5-handoff-v2` carries it. A rule flag cites only ids that exist in the package. |
| 4 | Zero and missing values | `value or 1` treated 0 as missing (HLS clear fraction 0 raised no flag). | 0 is a value. An absent or null fact raises no flag and is listed in `missing_facts`. |
| 5 | Timing flags | Hindsight and unknown sources were one "hindsight" flag. | Hindsight sources raise `hindsight_as_forecast`. Sources with unknown availability raise `missing_observations`. |
| 6 | Model identity | The served file name was compared with the registry. | The SHA-256 of the model file is computed before the side server starts it, and for Muse from the file that `/props` names. Digest time is recorded. |
| 7 | Participation | Role bindings showed configured checkpoints. | `council_executed` records which roles made a model call. The UI marks a configured role that did not run. |

## 3. Packages

- A to D: unchanged, same bytes and hashes. Package D keeps its version 1 availability classes.
  This is a limitation of D (FIRMS and IMERG Early are classed by nominal latency there).
- `e-m5-handoff`: unchanged. No council run used it.
- `e-m5-handoff-v2`: new. Built from the same M5 package (`m5-evidence-2`, commit `458f297`,
  the same package hash) with the corrected adapter. Its answer key was written before any run.
  Under the corrected rule, only NEA PM2.5 and IMERG Early are issue-time valid. The FIRMS
  standard-product archive is `unknown`.

## 4. Runs (in this order, one at a time)

1. Rescore every recorded critic run (no model call): `scripts/m41_critic_rescore.py`.
2. Council arms F, S, H, HC on A, B, C, D and `e-m5-handoff-v2`, temperature 0, seed 20261104.
3. Arm T on the same five packages.
4. Muse critic test on the 24 cases (the run under version 1 was stopped before it finished).
5. Repeat: arm H on A and `e-m5-handoff-v2`. Stochastic: arm HC on A, twice, temperature 1.0.

Arm HC8 does not run: Llama 3.1 8B detected no seeded fault under either contract, so it fails
the section 5 gates (Amendment 3). The rescored files confirm this.

## 5. Unchanged

Roles and checkpoints (Amendment 3), the critic gates, the council metrics, the disqualifiers,
the escalation rule and the human gate. A Muse critic is a separate role on the Lead's
checkpoint, not an independent model. No model approves adoption.

## Amendments

### Amendment 1 (2026-11-04): a missing essential quality fact excludes the source

- **Why.** Review of PR #117: a missing required measurement must not quietly permit an
  affirmative suitability recommendation.
- **Change.** In the design scenario, HLS needs `hls.clear` and SMAP needs `smap.rq`. If the
  fact is absent or null, the code rule excludes the source, raises `missing_observations`
  with the source id, and lists the fact in `missing_facts`. A proceeding plan that uses the
  source fails the `issue_time_inputs` check.
- **Effect on runs.** Written while the m41-v2 council runs were in progress. The code rule
  output is byte-identical on all six frozen packages before and after the change (checked in
  code), because none of them has an issue-time-valid HLS or SMAP source without its quality
  fact. No recorded run changes. Tests cover a measured fact, an absent fact and a null fact.

### Amendment 2 (2026-11-04): rule m41-v3 for integer measurements and overall deterioration

- **Why.** Final review of PR #117 found two defects in the code rule and the checks.
  1. The number check read decimals only. Integer measurements ("MAE of 29", "45%",
     "42 elevated days") were not checked.
  2. In the design scenario, the flag for "fire inputs make all-hour MAE worse and help the
     elevated hours" used `subgroup_deterioration`. That class means worse performance inside
     a subgroup. The case is an all-hour deterioration.
- **Change (prospective, m41-v3).**
  - `assess/numbers.py`: an integer is a measurement when a unit follows it or a metric word
    comes just before it. Years without a unit, identifiers (R2, T+6, p15), dates, times and
    thresholds ("above 55") are not. An integer is grounded when a package value rounds to it
    (within half a unit, or half a percent point). Package values include fact values, source
    latencies and cutoffs, and numbers in the package text.
  - New fault class `overall_deterioration`. The design rule uses it for the case above. The
    model-selection rule (models worse than persistence above 55) keeps
    `subgroup_deterioration`. The policy result reports `m41-v3`.
- **Effect on recorded results.** None. The m41-v2 runs, the answer keys, the 24 critic cases
  and their scores stay as recorded. An offline re-check of the recorded runs with the m41-v3
  number rule (`scripts/m41_recheck_numbers.py`, no model call) writes a separate evaluation
  file. On the 25 main runs it found no integer measurement that the package does not support.
- **Known consequence.** The rules-only critic under m41-v3 detects 5 of the 12 m41-v2 seeded
  faults, not 6. Case D-f3 carries the m41-v2 label `subgroup_deterioration`. A new critic
  test needs new labels for that case.
